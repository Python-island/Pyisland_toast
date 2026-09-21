import asyncio

import windows_bluetooth_watcher as wbw

CONNECTED_STATUS = "Connected"
ABORTED_HRESULT = "0x80004004"
QUERY_RETRIES = 2
QUERY_RETRY_DELAY = 0.35


def _is_aborted_error(error: Exception) -> bool:
    """判断是否为 Windows 在设备状态变化时产生的瞬时中止错误。"""
    return ABORTED_HRESULT.lower() in str(error).lower()


async def _get_devices(only_connected: bool = True):
    """通过 windows-bluetooth-watcher 获取蓝牙设备。

    上游库在不同版本间调整过 API：较新的文档提到 request_permission()，
    当前使用的 0.1.3 版本只暴露 get_all()。这里同时兼容两种形式。
    """
    for attempt in range(QUERY_RETRIES + 1):
        try:
            listener = wbw.Listener()

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
