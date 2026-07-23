"""
Echo Compass - 主程序
整合 WASAPI 捕获 + 方向计算 + 声音分类 + UI 显示

运行方式:
    python main.py
"""

import sys
import os
import threading
import time
import warnings
import numpy as np

# soundcard 在 WASAPI loopback 下偶发 "data discontinuity" 警告（少量丢帧），
# 对 onset 检测几乎无影响，过滤掉以免刷屏
warnings.filterwarnings('ignore', message='data discontinuity in recording')

from echo_compass.direction import analyze_audio_block
from echo_compass.classifier import classify_sound
from echo_compass.protocol import CompassData, serialize
from echo_compass.ui_tk import EchoCompassApp
from echo_compass.protocol import SOUND_TYPE_FOOTSTEP, SOUND_TYPE_GUNSHOT, SOUND_TYPE_OTHER, SOUND_TYPE_SILENCE
from echo_compass.web_radar import WebRadarServer, get_local_ip


SAMPLE_RATE = 48000
BLOCK_MS = 10  # 每块 10ms，降低延迟
UPDATE_HZ = 60  # UI 刷新率，提升响应速度
HOLD_SEC_FOOTSTEP = 0.3
HOLD_SEC_GUNSHOT = 0.15
ENV_RELEASE = 0.80
ANGLE_SMOOTH = 0.3

# 削顶保护：起音块波形峰值超过此值，认为削顶，左右响度差不可信，
# 这一发不重新锁方向，沿用上次角度
CLIP_THRESHOLD = 0.98

# 起音检测（onset）
# 基线用对称滑动平均，让基线跟着整体环境走（不至于贴到谷底让风声鸟叫都触发）
BASELINE_DECAY = 0.97   # 基线衰减系数，越大基线越稳但响应越慢
ONSET_RATIO = 4.0       # 瞬时能量需超过基线的倍数才判为起音（抬高挡住环境音正常起伏）
ONSET_FLOOR_DB = -52    # 绝对能量下限（dB），低于此值不触发
# 绝对响度直通：超过此 dB 不管基线高低直接算起音，枪声这种大动静永不漏
LOUD_ALWAYS_DB = -28    # 初始值，游戏里调
# 纯威胁雷达模式：开=True 时起音只走绝对响度直通，不走相对基线，安静时雷达绝不乱闪
# 关=False 回到灵敏模式（绝对直通 + 相对基线双路），用于追远处轻脚步
SIMPLE_MODE = True

# 手机端 Web 雷达（第二块屏）：起本地 HTTP 服务，手机浏览器打开就是罗盘页面
# 起不来或没人连都不影响主程序
WEB_PORT = 8090

# 屏蔽自身声音（分两档，防交火时转身瞄敌人反而被屏蔽）
# 自己声音的特点：特别响 + 死死钉在 0 度（几乎不晃）
# 敌人就算被我瞄准，角度也总有一两度晃动
#   特别响(> SELF_DB_VERY_LOUD)：基本只可能是自己开枪，正中 SELF_ANGLE_DEAD 内屏蔽
#   中等响(SELF_DB_THRESHOLD ~ SELF_DB_VERY_LOUD)：只屏蔽几乎精确 0 度（SELF_ANGLE_DEAD_TIGHT 内）
SELF_DB_THRESHOLD = -20      # 中等响下限(dB)，低于此值不屏蔽
SELF_DB_VERY_LOUD = -6       # 特别响门槛(dB)，超过此值基本是自己开枪，初始值，游戏里调
SELF_ANGLE_DEAD = 3          # 特别响时的正中死区宽度(度)，初始值，游戏里调
SELF_ANGLE_DEAD_TIGHT = 1    # 中等响时的死区宽度(度)，自己声音死钉 0 度，初始值，游戏里调

# 枪声快速判定：起音时响度超过此值(dB) 直接判枪声，绕过分类器
# 枪声比脚步响得多，用响度一刀切最稳
GUNSHOT_ONSET_DB = -18     # 初始值，游戏里校


class AudioCaptureThread(threading.Thread):
    """音频捕获 + 处理线程"""
    
    def __init__(self, on_data_callback, sample_rate=SAMPLE_RATE):
        super().__init__(daemon=True)
        self.on_data = on_data_callback
        self.sample_rate = sample_rate
        self._running = False
        self._status_callback = None
        # 时间平滑 / 事件保持状态
        self._env_energy = 0.0
        self._last_event_time = 0.0
        self._smooth_angle = None
        self._peak_energy = 0.0       # 当前事件能量峰值，用于角度锁存
        self._last_sound_type = SOUND_TYPE_OTHER
        self._last_confidence = 0.0
        self._baseline = None          # 起音检测基线（首次捕获时校准）
        # 事件类型锁：起音那一下定死类型，整个事件期间不变，声音结束才重置
        # 仿方向锁：避免延音块走分类平滑把枪声拽回脚步
        self._event_type_locked = False
        self._event_sound_type = SOUND_TYPE_OTHER
        # 方向锁存：起音后锁住方向，直到声音结束才重新算
        self._direction_locked = False
        self._onset_total_e = 0.0      # 起音时的总能量，用于枪声快速判定

    def set_status_callback(self, cb):
        self._status_callback = cb
    
    def _status(self, text):
        if self._status_callback:
            self._status_callback(text)
    
    def stop(self):
        self._running = False
    
    def _make_display_data(self, analysis, classification, now):
        """把每块的瞬时结果做时间平滑 + 事件保持，给 UI 稳定的数据。

        距离用能量包络（瞬时峰值立即跟上、之后缓慢回落）换算，避免脚步/枪声
        本身的起伏让光点远近乱跳；声音停止后保持 HOLD_SEC 再熄灭，避免闪烁。
        """
        if analysis['has_sound']:
            inst = analysis['total_energy']
            # 能量包络：攻击瞬时、释放缓慢
            if inst >= self._env_energy:
                self._env_energy = inst
            else:
                self._env_energy = self._env_energy * ENV_RELEASE + inst * (1 - ENV_RELEASE)
            self._last_event_time = now

            # 方向锁存：起音那一下定死，后续块不再更新，直到声音结束
            if not self._direction_locked:
                self._smooth_angle = analysis['angle']
                self._direction_locked = True

            self._last_confidence = analysis['confidence']
            # 类型已由起音块锁定（_event_sound_type），整个事件期间不变
            self._last_sound_type = self._event_sound_type
        else:
            # 没声音：保持时间内继续显示（能量缓降），超时才熄灭
            # 保持时间按当前事件类型选
            hold_sec = HOLD_SEC_GUNSHOT if self._event_sound_type == SOUND_TYPE_GUNSHOT else HOLD_SEC_FOOTSTEP
            if now - self._last_event_time > hold_sec:
                self._env_energy = 0.0
                self._peak_energy = 0.0  # 重置峰值
                self._smooth_angle = None
                self._direction_locked = False  # 声音结束，解锁方向
                self._event_type_locked = False  # 声音结束，解锁类型
                return CompassData()
            self._env_energy *= ENV_RELEASE

        e = self._env_energy
        if e < 1e-10 or self._smooth_angle is None:
            return CompassData()

        # 被动 loopback 的能量算不出真实距离，固定光点在固定中外圈
        distance = 0.6

        angle = self._smooth_angle
        while angle < 0:
            angle += 360
        while angle >= 360:
            angle -= 360

        data = CompassData()
        data.has_sound = True
        data.angle = angle
        data.distance = distance
        data.energy = min(1.0, e / 0.5)
        data.confidence = self._last_confidence
        data.sound_type = self._last_sound_type
        return data

    def run(self):
        self._running = True
        
        try:
            import soundcard as sc
        except ImportError:
            self._status('错误: soundcard 库未安装')
            return

        # 找 loopback 设备：直接抓系统默认播放设备的 loopback（2 声道，HRTF 模式）
        try:
            all_mics = sc.all_microphones(include_loopback=True)
            loopback = None

            # 找默认播放设备对应的 loopback
            try:
                default_speaker_name = sc.default_speaker().name
                for m in all_mics:
                    if m.isloopback and m.name == default_speaker_name:
                        loopback = m
                        break
            except Exception:
                pass

            # 兜底：找任意 loopback
            if loopback is None:
                for m in all_mics:
                    if m.isloopback:
                        loopback = m
                        break

            if loopback is None:
                self._status('错误: 未找到 WASAPI Loopback 设备')
                return

            # 双耳模式：只抓 2 声道（立体声 / HRTF）
            channels = min(2, loopback.channels)
            self._status(f'捕获: {loopback.name} ({channels} 声道, 双耳模式)')

        except Exception as e:
            self._status(f'错误: 无法初始化音频设备 - {e}')
            return

        blocksize = int(self.sample_rate * BLOCK_MS / 1000)

        try:
            with loopback.recorder(samplerate=self.sample_rate, channels=channels,
                                    blocksize=blocksize) as rec:

                last_update = 0
                update_interval = 1.0 / UPDATE_HZ

                while self._running:
                    try:
                        data = rec.record(blocksize)

                        if data is None or data.size == 0:
                            time.sleep(0.01)
                            continue

                        # 分析音频块
                        analysis = analyze_audio_block(data, method='weighted')

                        # 起音检测（onset）：用能量基线 + 比值判断，替代"音量过线就算有声"
                        total_e = analysis['total_energy']
                        total_db = 20 * np.log10(total_e + 1e-10)
                        if self._baseline is None:
                            # 启动校准：第一块直接当基线，避免开头全判为 onset
                            self._baseline = total_e
                        # 对称滑动平均更新基线，跟着整体环境走
                        self._baseline = self._baseline * BASELINE_DECAY + total_e * (1 - BASELINE_DECAY)
                        # 起音判定：
                        #   SIMPLE_MODE=True（纯威胁雷达）：只走绝对响度直通，安静时绝不乱闪
                        #   SIMPLE_MODE=False（灵敏模式）：绝对直通 + 相对基线双路，追远处轻脚步
                        if SIMPLE_MODE:
                            is_onset = (total_db > LOUD_ALWAYS_DB) and (total_db > ONSET_FLOOR_DB)
                        else:
                            is_onset = ((total_e > self._baseline * ONSET_RATIO) or (total_db > LOUD_ALWAYS_DB)) \
                                       and (total_db > ONSET_FLOOR_DB)
                        # 包络持续保持：onset 触发后，用能量包络维持 has_sound，
                        # 包络高于噪声底期间一直显示，不再依赖每块都触发 onset
                        if is_onset:
                            analysis['has_sound'] = True
                            # 削顶保护：起音块波形峰值超 CLIP_THRESHOLD，左右响度差不可信
                            peak = float(np.max(np.abs(data))) if data.size > 0 else 0.0
                            if peak > CLIP_THRESHOLD:
                                if self._smooth_angle is not None:
                                    pass  # 削顶且已有角度：保持锁定，沿用上次角度
                                else:
                                    analysis['angle'] = 0.0  # 削顶且之前没角度：放正中
                                    self._direction_locked = False
                            else:
                                self._direction_locked = False  # 没削顶：正常解锁重新算
                            self._event_type_locked = False  # 新起音，解锁类型（跟方向同节奏）
                            self._onset_total_e = total_e    # 记录起音能量，用于枪声判定
                        elif self._env_energy > self._baseline * 1.5:
                            analysis['has_sound'] = True
                        else:
                            analysis['has_sound'] = False

                        # 屏蔽自身声音（分两档）
                        if analysis['has_sound']:
                            total_db = 20 * np.log10(analysis['total_energy'] + 1e-10)
                            # 把 angle 归一化到 ±180
                            a = analysis['angle']
                            while a > 180:
                                a -= 360
                            while a <= -180:
                                a += 360
                            # 特别响(> SELF_DB_VERY_LOUD)：基本是自己开枪，正中 SELF_ANGLE_DEAD 内屏蔽
                            # 中等响(SELF_DB_THRESHOLD ~ SELF_DB_VERY_LOUD)：只屏蔽几乎精确 0 度(SELF_ANGLE_DEAD_TIGHT 内)
                            # 这样交火时转身瞄敌人(中等响+正中1~3度)不会误伤
                            if total_db > SELF_DB_VERY_LOUD and abs(a) <= SELF_ANGLE_DEAD:
                                analysis['has_sound'] = False
                            elif total_db > SELF_DB_THRESHOLD and abs(a) <= SELF_ANGLE_DEAD_TIGHT:
                                analysis['has_sound'] = False

                        # 类型锁：起音块每次都重定类型（跟方向锁同节奏），锁只拦延音块
                        # 避免延音块走分类器把枪声拽回脚步；脚步中突然开枪是新起音，会重定类型
                        if analysis['has_sound']:
                            if is_onset:
                                # 起音块：定类型（每次起音都重定，不拦）
                                if total_db > GUNSHOT_ONSET_DB:
                                    self._event_sound_type = SOUND_TYPE_GUNSHOT
                                else:
                                    cls = classify_sound(data)
                                    self._event_sound_type = (SOUND_TYPE_GUNSHOT
                                                              if cls['type'] == 'gunshot'
                                                              else SOUND_TYPE_FOOTSTEP)
                                self._event_type_locked = True
                            # 延音块：类型已锁，沿用 _event_sound_type，不调分类器
                            classification = {
                                'type': 'gunshot' if self._event_sound_type == SOUND_TYPE_GUNSHOT else 'footstep',
                                'confidence': 0.9, 'features': {},
                            }
                        else:
                            classification = {'type': 'silence', 'confidence': 1.0, 'features': {}}

                        # 时间平滑 + 事件保持，避免光点远近/方向乱跳
                        now = time.time()
                        compass_data = self._make_display_data(analysis, classification, now)

                        # 限制 UI 更新频率
                        if now - last_update >= update_interval:
                            last_update = now
                            self.on_data(compass_data)

                    except Exception as e:
                        self._status(f'捕获错误: {e}')
                        time.sleep(0.1)

        except Exception as e:
            self._status(f'录音器错误: {e}')
            return


def find_compass_port():
    """自动查找圆屏的串口（CH343 / USB-SERIAL CH / VID 1A86 / VID 303A）"""
    try:
        from serial.tools import list_ports
    except ImportError:
        return None

    ports = list(list_ports.comports())

    # 第一优先级：描述含 CH343 / USB-SERIAL CH / USB 串行
    for p in ports:
        desc = (p.description or '').lower()
        if 'ch343' in desc or 'usb-serial ch' in desc or 'usb 串行' in desc:
            return p.device

    # 第二优先级：VID 匹配
    for p in ports:
        hwid = (p.hwid or '').upper()
        if 'VID:PID=1A86' in hwid or 'VID_1A86' in hwid:
            return p.device
        if 'VID:PID=303A' in hwid or 'VID_303A' in hwid:
            return p.device

    return None


class SerialSender:
    """串口发送（可选，硬件到位后启用）"""

    def __init__(self):
        self.serial = None
        self.port = None

    def connect(self, port):
        try:
            import serial
            self.serial = serial.Serial(port, 115200, timeout=0.1)
            self.port = port
            return True
        except Exception as e:
            print(f'串口连接失败: {e}')
            return False

    def send(self, data: CompassData):
        if self.serial is None:
            return
        try:
            frame = serialize(data)
            self.serial.write(frame)
        except Exception:
            pass

    def close(self):
        if self.serial:
            self.serial.close()
            self.serial = None


def main():
    app = EchoCompassApp()

    serial_sender = SerialSender()

    # 启动时自动查找并连接圆屏串口
    status_parts = []
    port = find_compass_port()
    if port:
        if serial_sender.connect(port):
            status_parts.append(f'圆屏 {port}')
        else:
            status_parts.append('无圆屏')
    else:
        status_parts.append('无圆屏')

    # 启动手机端 Web 雷达（第二块屏），失败不影响主程序
    web_server = WebRadarServer(port=WEB_PORT)
    web_addr = ''
    if web_server.start():
        ip = get_local_ip()
        web_addr = f'Web http://{ip}:{WEB_PORT}'
        status_parts.append(web_addr)
    # 起不来就静默，主程序照跑

    app.set_status(' | '.join(status_parts))

    # 音频线程的 status 回调会覆盖，这里包一层，把 web 地址拼上
    def status_callback(text):
        if web_addr:
            app.set_status(f'{text} | {web_addr}')
        else:
            app.set_status(text)

    def on_data(data: CompassData):
        app.set_data(data)
        # 串口和 web 各发一份
        serial_sender.send(data)
        web_server.push({
            'has_sound': data.has_sound,
            'angle': data.angle,
            'distance': data.distance,
            'sound_type': data.sound_type,
            'energy': data.energy,
            'confidence': data.confidence,
        })

    capture_thread = AudioCaptureThread(on_data)
    capture_thread.set_status_callback(status_callback)
    capture_thread.start()

    try:
        app.run()
    finally:
        capture_thread.stop()
        serial_sender.close()
        web_server.stop()


if __name__ == '__main__':
    main()
