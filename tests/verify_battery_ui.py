"""在真实 QtWebEngine 中检查电池 Toast；需要先构建前端，不改变系统电源。"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication

from pyisland_toast.app import ToastWindow

QApplication.setAttribute(Qt.AA_ShareOpenGLContexts, True)
app = QApplication([])
app.setQuitOnLastWindowClosed(False)
window = ToastWindow()
failures = []
cases = [
    ('red', '电源已连接', 10, 'charging'),
    ('yellow', '电源已连接', 45, 'charging'),
    ('green', '电源已连接', 85, 'charging'),
    ('empty', '电源已连接', 0, 'charging'),
    ('full', '电源已连接', 100, 'charging'),
    ('unknown', '电源已连接', None, 'charging'),
    ('unplugged', '电源已断开', 65, 'default'),
    ('low', '电量不足', 15, 'default'),
]

PROBE = """
(() => {
  const bar = document.querySelector('.snackbar');
  const fill = document.querySelector('.charging-fill');
  const label = document.querySelector('.snackbar__battery-level');
  return JSON.stringify({
    count: document.querySelectorAll('.snackbar').length,
    mode: bar?.className,
    width: bar?.getBoundingClientRect().width,
    fill: fill?.style.width ?? null,
    background: fill ? getComputedStyle(fill).backgroundImage : null,
    level: label?.textContent ?? null,
    svg: document.querySelectorAll('.snackbar__lottie svg').length,
    shadow: bar ? getComputedStyle(bar).boxShadow : null
  });
})()
"""


def check(case, raw):
    tag, _, percent, variant = case
    try:
        result = json.loads(raw)
        assert result['count'] == 1, result
        assert result['svg'] == 1 and 'icon-lottie' in result['mode'], result
        assert result['width'] <= 420, result
        assert result['shadow'] == 'none', result
        if variant == 'charging':
            assert result['fill'] == f'{percent or 0}%', result
            assert result['level'] == ('电量未知' if percent is None else f'{percent}%'), result
            expected_color = ('180, 35, 53' if (percent or 0) <= 20
                              else '136, 96, 20' if percent <= 60 else '18, 99, 74')
            assert expected_color in result['background'], result
        else:
            assert result['fill'] is None and result['level'] is None, result
        print(f'PASS {tag}: {raw}', flush=True)
    except Exception as exc:
        failures.append(f'{tag}: {exc}')
        print(f'FAIL {tag}: {exc}', flush=True)


def probe(case):
    window.view.page().runJavaScript(PROBE, 0, lambda raw: check(case, raw))


def send(case):
    _, kind, percent, variant = case
    window.show_battery_toast({
        'message': f'电池电量仅剩{percent}%' if kind == '电量不足' else kind,
        'type': kind, 'duration': 1600, 'variant': variant,
        'battery': {'percent': percent, 'charging': variant == 'charging'},
    })


started = False


def loaded(ok):
    global started
    if started or not ok:
        return
    started = True
    # 先验证睡眠拦截，不需要真的进入游戏或更改系统电源模式。
    payloads = []
    window.bridge.toastRequested.connect(payloads.append)
    window.set_sleeping(True)
    send(cases[0])
    if payloads:
        failures.append('sleep gate failed')
    window.set_sleeping(False)
    for index, case in enumerate(cases):
        delay = 800 + index * 2400
        QTimer.singleShot(delay, lambda item=case: send(item))
        QTimer.singleShot(delay + 1200, lambda item=case: probe(item))
    QTimer.singleShot(800 + len(cases) * 2400, finish)


def finish():
    if not started:
        failures.append('frontend failed to load')
    print(f'Battery UI verification: {len(failures)} failure(s)', flush=True)
    window.close()
    app.exit(1 if failures else 0)


window.frontendReady.connect(loaded)
window.show()
QTimer.singleShot(0, window.init_webengine)
QTimer.singleShot(30000, finish)
sys.exit(app.exec())
