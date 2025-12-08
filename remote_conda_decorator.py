import os
import uuid
import sys
import shutil
import subprocess
import time
from functools import wraps
import dill as pickle 

# ==========================================
#  1. SmartAnnData 定义 (本地 Notebook 用)
# ==========================================
class SmartAnnData:
    """
    智能 AnnData 包装器：
    利用 Linux /dev/shm (内存盘) 进行零拷贝传输。
    """
    def __init__(self, adata, mode='r+'):
        self.adata = adata
        self.temp_path = None
        self.mode = mode

    def __getstate__(self):
        # 序列化时：保存 adata 到内存文件，只传递路径
        unique_id = str(uuid.uuid4())
        self.temp_path = f"/dev/shm/adata_{unique_id}.h5ad"
        print(f"⚡ [SmartAnnData] Saving AnnData to RAM disk: {self.temp_path} ...")
        try:
            import anndata
            self.adata.write_h5ad(self.temp_path)
        except ImportError:
            raise ImportError("Local environment must have 'anndata' installed.")
        return {'temp_path': self.temp_path, 'mode': self.mode}

    def __setstate__(self, state):
        # 反序列化时：从内存文件加载 adata
        self.temp_path = state['temp_path']
        self.mode = state['mode']
        try:
            import anndata
            self.adata = anndata.read_h5ad(self.temp_path)
            print(f"⚡ [SmartAnnData] Loaded AnnData from RAM disk in remote env.")
        except ImportError:
            raise ImportError("Remote environment must have 'anndata' installed.")

    def cleanup(self):
        # 清理临时文件
        if self.temp_path and os.path.exists(self.temp_path):
            try:
                os.remove(self.temp_path)
                print(f"🧹 [SmartAnnData] Cleaned up {self.temp_path}")
            except OSError:
                pass

# ==========================================
#  2. 动态生成远程脚本
# ==========================================
def _get_remote_script_template():
    
    # 手动定义的类源码字符串
    smart_class_source = """
class SmartAnnData:
    def __init__(self, adata, mode='r+'):
        self.adata = adata
        self.temp_path = None
        self.mode = mode

    def __getstate__(self):
        import uuid
        unique_id = str(uuid.uuid4())
        self.temp_path = f"/dev/shm/adata_{unique_id}.h5ad"
        print(f"⚡ [SmartAnnData] Saving AnnData to RAM disk: {self.temp_path} ...")
        try:
            import anndata
            self.adata.write_h5ad(self.temp_path)
        except ImportError:
            raise ImportError("Local environment must have 'anndata' installed.")
        return {'temp_path': self.temp_path, 'mode': self.mode}

    def __setstate__(self, state):
        self.temp_path = state['temp_path']
        self.mode = state['mode']
        try:
            import anndata
            self.adata = anndata.read_h5ad(self.temp_path)
            print(f"⚡ [SmartAnnData] Loaded AnnData from RAM disk in remote env.")
        except ImportError:
            raise ImportError("Remote environment must have 'anndata' installed.")

    def cleanup(self):
        import os
        if self.temp_path and os.path.exists(self.temp_path):
            try:
                os.remove(self.temp_path)
                print(f"🧹 [SmartAnnData] Cleaned up {self.temp_path}")
            except OSError:
                pass
"""
    
    # 使用 replace 注入源码
    script = """
import dill as pickle
import sys
import traceback
import os
import uuid

# [注入点] 这是一个占位符，稍后用 replace 替换
__SMART_CLASS_SOURCE_PLACEHOLDER__

def execute():
    try:
        input_file = sys.argv[1]
        
        with open(input_file, 'rb') as f:
            data = pickle.load(f)

        func = data['func']
        args = data['args']
        kwargs = data['kwargs']
        
        if 'cwd' in data:
            if data['cwd'] not in sys.path:
                sys.path.insert(0, data['cwd'])

        # 执行函数
        result = func(*args, **kwargs)
        
        response = {'result': result, 'error': None}

    except Exception as e:
        tb = traceback.format_exc()
        response = {'result': None, 'error_msg': str(e), 'traceback': tb}

    try:
        output_file = f"/dev/shm/result_{uuid.uuid4()}.pkl"
        
        with open(output_file, 'wb') as f:
            pickle.dump(response, f)
            
        print(f"RESULT_PATH:{output_file}", flush=True)
        
    except Exception as e:
        print(f"Critical error writing result: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    execute()
"""
    return script.replace("__SMART_CLASS_SOURCE_PLACEHOLDER__", smart_class_source)

# ==========================================
#  3. 装饰器主逻辑
# ==========================================
def wrap(base):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            input_path = f"/dev/shm/input_{uuid.uuid4()}.pkl"
            result_path = None
            
            try:
                data_to_send = {
                    'func': func,
                    'args': args,
                    'kwargs': kwargs,
                    'cwd': os.getcwd() 
                }
                
                with open(input_path, 'wb') as f:
                    pickle.dump(data_to_send, f)
                
                remote_script = _get_remote_script_template()
                
                command = [
                    'conda', 'run', '--no-capture-output', '-n', base,
                    'python', '-u', '-c', remote_script,
                    input_path
                ]
                
                process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                
                while True:
                    line = process.stdout.readline()
                    if not line and process.poll() is not None: break
                    if line:
                        stripped = line.strip()
                        if stripped.startswith("RESULT_PATH:"):
                            result_path = stripped.split(":", 1)[1]
                        else:
                            print(f"[{base}] {stripped}")

                if process.poll() != 0:
                    err = process.stderr.read()
                    raise RuntimeError(f"Remote Error (Exit {process.poll()}):\n{err}")

                if not result_path:
                    raise RuntimeError("No result path received from remote.")

                if not os.path.exists(result_path):
                     raise RuntimeError(f"Result file missing: {result_path}")

                with open(result_path, 'rb') as f:
                    result_data = pickle.load(f)
                
                if result_data.get('error_msg'):
                    print("="*20 + " REMOTE ERROR " + "="*20)
                    print(result_data['traceback'])
                    print("="*54)
                    raise RuntimeError(f"Remote process failed: {result_data['error_msg']}")
                
                final_result = result_data['result']
                
                # [关键修复] 使用类名检查代替 isinstance
                # 这样可以忽略 notebook 运行导致的类ID不一致问题
                if type(final_result).__name__ == 'SmartAnnData':
                    final_result = final_result.adata
                
                return final_result

            finally:
                if os.path.exists(input_path):
                    os.remove(input_path)
                if result_path and os.path.exists(result_path):
                    os.remove(result_path)
                for arg in args:
                    if isinstance(arg, SmartAnnData):
                        arg.cleanup()

        return wrapper
    return decorator