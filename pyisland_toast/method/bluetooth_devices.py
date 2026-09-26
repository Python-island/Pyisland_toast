import asyncio

# 导入 Rust 编写的原生扩展 windows-bluetooth-watcher（项目 bluetooth/ 目录下）。
# 它通过 Windows Runtime API 监听蓝牙设备状态变化，比 PowerShell/WMI 更可靠。
import windows_bluetooth_watcher as wbw

CONNECTED_STATUS = "Connected"            # 设备已连接的状态字符串
ABORTED_HRESULT = "0x80004004"            # Windows 操作被中止时的 HRESULT（E_ABORT）
QUERY_RETRIES = 2                         # 查询失败时的重试次数
QUERY_RETRY_DELAY = 0.35                  # 重试之间的基础延迟（秒），会随次数递增


def _is_aborted_error(error: Exception) -> bool:
    """判断是否为 Windows 在设备状态变化时产生的瞬时中止错误。

    当蓝牙设备正在连接/断开时，系统查询可能返回 E_ABORT，这是正常的瞬时现象，
    只需稍等重试即可，不应作为真正的错误处理。
    """
    return ABORTED_HRESULT.lower() in str(error).lower()


async def _get_devices(only_connected: bool = True):
    """通过 windows-bluetooth-watcher 获取蓝牙设备。

    上游库在不同版本间调整过 API：较新的文档提到 request_permission()，
    当前使用的 0.1.3 版本只暴露 get_all()。这里同时兼容两种形式。

    Args:
        only_connected: True 时只返回当前已连接的设备。
    """
    for attempt in range(QUERY_RETRIES + 1):
        try:
            listener = wbw.Listener()

            # 兼容新旧 API：如果有 request_permission 则先请求蓝牙权限
            request_permission = getattr(listener, "request_permission", None)
            if request_permission is not None:
                permission = await request_permission()
                if permission != "Allowed":
                    raise PermissionError(
                        f"Bluetooth permission not granted: {permission}"
                    )

            devices = await listener.get_all()
            break
        except Exception as error:
            # 只有"中止"错误才重试，其他错误直接抛出
            if not _is_aborted_error(error) or attempt >= QUERY_RETRIES:
                raise
            await asyncio.sleep(QUERY_RETRY_DELAY * (attempt + 1))

    if only_connected:
        devices = [d for d in devices if d.status == CONNECTED_STATUS]
    return devices


async def get_connected_devices():
    """只返回 watcher 状态为 Connected 的设备。"""
    return await _get_devices(only_connected=True)


async def get_all_devices():
    """返回 Windows watcher 报告的全部蓝牙设备。"""
    return await _get_devices(only_connected=False)


def get_connected_devices_sync():
    """供脚本和简单诊断使用的同步封装。"""
    return asyncio.run(get_connected_devices())


def get_all_devices_sync():
    """供脚本和简单诊断使用的同步封装。"""
    return asyncio.run(get_all_devices())