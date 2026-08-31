"""SSH 远程执行层（asyncssh + 常驻后台事件循环线程）

所有调用方（任务执行线程、巡检线程、API 请求线程）都在同步上下文中，
而 asyncssh 是异步库且连接绑定事件循环。这里用一个常驻后台线程跑
事件循环，对外暴露同步 API，内部通过 run_coroutine_threadsafe 提交协程，
连接池绑定该循环实现跨调用复用。

连接参数 machine 为 dict：{host, port, username, auth_type, key_path,
password_enc}（由 models.NpuMachine.to_ssh_params() 生成）。
"""
import asyncio
import logging
import os
import threading
from typing import Callable, Dict, List, Optional, Tuple

import asyncssh
from cryptography.fernet import Fernet, InvalidToken

from app.config import Config

logger = logging.getLogger(__name__)


class SshCommandTimeout(Exception):
    """远程命令执行超时"""


class SshConnectError(Exception):
    """SSH 连接失败（认证/网络等）"""


# ----------------------------------------------------------------------
# 常驻后台事件循环
# ----------------------------------------------------------------------

_loop: Optional[asyncio.AbstractEventLoop] = None
_loop_lock = threading.Lock()


def _get_loop() -> asyncio.AbstractEventLoop:
    """获取（懒启动）常驻事件循环，专用于 asyncssh 协程"""
    global _loop
    with _loop_lock:
        if _loop is None or _loop.is_closed():
            _loop = asyncio.new_event_loop()
            t = threading.Thread(target=_loop.run_forever, daemon=True, name="npu-ssh-loop")
            t.start()
        return _loop


def run_sync(coro, timeout: Optional[float] = None):
    """在当前线程同步等待协程在后台循环上执行完成"""
    future = asyncio.run_coroutine_threadsafe(coro, _get_loop())
    return future.result(timeout=timeout)


def decrypt_password(password_enc: str) -> str:
    """解密 NPU 机器 SSH 密码"""
    try:
        return Fernet(Config.get_npu_secret_key()).decrypt(password_enc.encode()).decode()
    except (InvalidToken, ValueError) as e:
        raise SshConnectError("SSH 密码解密失败：NPU_SECRET_KEY 与加密时不一致（可能更换过密钥）") from e


# ----------------------------------------------------------------------
# 连接池（machine_id -> SSHClient），绑定后台事件循环
# ----------------------------------------------------------------------

_conns: Dict[Tuple, asyncssh.SSHClientConnection] = {}
_conn_locks: Dict[Tuple, asyncio.Lock] = {}


def _conn_key(machine: dict) -> Tuple:
    return (machine["host"], machine.get("port") or 22, machine["username"])


def drop_conn(machine: dict) -> None:
    """主动丢弃某机器的缓存连接（机器配置变更/连接报错后调用）"""
    key = _conn_key(machine)
    conn = _conns.pop(key, None)
    if conn:
        try:
            conn.close()
        except Exception:
            pass


async def _connect(machine: dict) -> asyncssh.SSHClientConnection:
    key = _conn_key(machine)
    lock = _conn_locks.setdefault(key, asyncio.Lock())
    async with lock:
        conn = _conns.get(key)
        if conn is not None:
            # 发送空操作检测连接存活（is_closed 不总能及时反映断连）
            if not conn.is_closed():
                return conn
            _conns.pop(key, None)

        kwargs = dict(known_hosts=None, connect_timeout=15)
        if machine.get("auth_type") == "password":
            enc = machine.get("password_enc") or ""
            if not enc:
                raise SshConnectError("机器未配置密码")
            kwargs["password"] = decrypt_password(enc)
        else:
            key_content_enc = machine.get("key_content_enc") or ""
            key_path = machine.get("key_path") or ""
            if key_content_enc:
                # 私钥内容（前端粘贴/文件读取，Fernet 加密存储），无需服务端密钥文件
                try:
                    kwargs["client_keys"] = [asyncssh.import_private_key(decrypt_password(key_content_enc))]
                except (asyncssh.KeyImportError, ValueError) as e:
                    raise SshConnectError(f"私钥内容无效: {e}") from e
            elif key_path:
                expanded = os.path.expanduser(key_path)
                if not os.path.exists(expanded):
                    raise SshConnectError(f"私钥文件不存在: {key_path}")
                kwargs["client_keys"] = [expanded]
            else:
                raise SshConnectError("机器未配置私钥（内容或路径）")

        try:
            conn = await asyncssh.connect(
                machine["host"], port=machine.get("port") or 22,
                username=machine["username"], **kwargs,
            )
        except (OSError, asyncssh.Error) as e:
            raise SshConnectError(f"SSH 连接失败 {machine['username']}@{machine['host']}: {e}") from e
        _conns[key] = conn
        return conn


async def _run_cmd(machine: dict, cmd: str, timeout: Optional[float],
                   on_output: Optional[Callable[[str, str], None]]):
    conn = await _connect(machine)
    stdout_buf: List[str] = []
    stderr_buf: List[str] = []

    proc = await conn.create_process(cmd)

    async def _pump(stream, buf: List[str], tag: str):
        while True:
            data = await stream.read(8192)
            if not data:
                break
            buf.append(data)
            if on_output:
                try:
                    on_output(tag, data)
                except Exception:
                    logger.exception("on_output callback failed")

    tasks = [
        asyncio.create_task(_pump(proc.stdout, stdout_buf, "stdout")),
        asyncio.create_task(_pump(proc.stderr, stderr_buf, "stderr")),
    ]
    try:
        result = await asyncio.wait_for(proc.wait(), timeout=timeout)
    except asyncio.TimeoutError:
        try:
            proc.kill()
            await proc.wait()
        except Exception:
            pass
        raise SshCommandTimeout(f"命令超时（{timeout}s）: {cmd[:120]}")
    finally:
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    # asyncssh 的 proc.wait() 返回 SSHCompletedProcess 对象而非 int，
    # 统一归一化为退出码（信号终止时 exit_status 为空，回退 returncode/-1）
    if isinstance(result, asyncssh.SSHCompletedProcess):
        exit_status = result.exit_status
        if exit_status is None:
            exit_status = getattr(result, "returncode", None)
        if exit_status is None:
            exit_status = -1
    else:
        exit_status = int(result)

    return exit_status, "".join(stdout_buf), "".join(stderr_buf)


# ----------------------------------------------------------------------
# 对外同步 API
# ----------------------------------------------------------------------

def run_command(machine: dict, cmd: str, timeout: Optional[float] = 300,
                on_output: Optional[Callable[[str, str], None]] = None) -> Tuple[int, str, str]:
    """在机器上执行 shell 命令，返回 (exit_code, stdout, stderr)。

    on_output(tag, chunk) 用于实时获取输出（tag 为 'stdout'/'stderr'）。
    """
    try:
        return run_sync(_run_cmd(machine, cmd, timeout, on_output), timeout=(timeout or 300) + 30)
    except SshCommandTimeout:
        raise
    except SshConnectError:
        raise
    except Exception as e:
        raise SshConnectError(f"命令执行异常: {e}") from e


def test_connection(machine: dict) -> Tuple[bool, str]:
    """测试 SSH 连通性，返回 (ok, message)"""
    try:
        code, out, err = run_command(machine, "echo ok", timeout=20)
        return (code == 0 and "ok" in out), (out.strip() if code == 0 else err.strip()[:300])
    except Exception as e:
        return False, str(e)[:300]


def list_dir(machine: dict, path: str) -> List[dict]:
    """SFTP 列出目录内容（含文件大小/修改时间），供 profiling 文件浏览"""
    path = os.path.expanduser(path)

    async def _list():
        conn = await _connect(machine)
        async with conn.start_sftp_client() as sftp:
            entries = []
            for attr in await sftp.listdir(path):
                full = f"{path.rstrip('/')}/{attr.filename}"
                stat = None
                try:
                    stat = await sftp.stat(full)
                except Exception:
                    pass
                entries.append({
                    "name": attr.filename,
                    "size": getattr(stat, "size", 0) or 0,
                    "mtime": getattr(stat, "mtime", None),
                    "is_dir": stat and stat.permissions is not None and (stat.permissions & 0o040000) != 0,
                })
            entries.sort(key=lambda x: x["name"])
            return entries

    return run_sync(_list(), timeout=60)


def download_file(machine: dict, remote_path: str, local_path: str) -> str:
    """SFTP 下载远程文件到本地路径，返回本地路径"""
    remote_path = os.path.expanduser(remote_path)

    async def _download():
        conn = await _connect(machine)
        async with conn.start_sftp_client() as sftp:
            await sftp.get(remote_path, local_path)

    run_sync(_download(), timeout=600)
    return local_path


def make_dir(machine: dict, remote_path: str) -> None:
    """SFTP 递归创建远程目录"""
    remote_path = os.path.expanduser(remote_path)

    async def _mkdir():
        conn = await _connect(machine)
        async with conn.start_sftp_client() as sftp:
            parts = remote_path.strip("/").split("/")
            cur = ""
            for part in parts:
                cur += "/" + part
                try:
                    await sftp.stat(cur)
                except FileNotFoundError:
                    try:
                        await sftp.mkdir(cur)
                    except FileExistsError:
                        pass

    run_sync(_mkdir(), timeout=60)
