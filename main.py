"""
Echo Compass - 主程序
整合 WASAPI 捕获 + 方向计算 + 声音分类 + UI 显示
"""

import sys
import os
import threading
import time
import warnings
import numpy as np

warnings.filterwarnings('ignore', message='data discontinuity in recording')

from echo_compass.direction import analyze_audio_block
from echo_compass.classifier import classify_sound
from echo_compass.protocol import CompassData, serialize
from echo_compass.ui_tk import EchoCompassApp
from echo_compass.protocol import SOUND_TYPE_FOOTSTEP, SOUND_TYPE_GUNSHOT, SOUND_TYPE_OTHER, SOUND_TYPE_SILENCE
from echo_compass.web_radar import WebRadarServer, get_local_ip


SAMPLE_RATE = 48000
BLOCK_MS = 10
UPDATE_HZ = 60
HOLD_SEC_FOOTSTEP = 0.3
HOLD_SEC_GUNSHOT = 0.15
ENV_RELEASE = 0.80
ANGLE_SMOOTH = 0.2

CLIP_THRESHOLD = 0.95
CLIP_WARNING_THRESHOLD = 0.85

BASELINE_DECAY = 0.96
ONSET_RATIO = 3.5
ONSET_FLOOR_DB = -55
LOUD_ALWAYS_DB = -28
SIMPLE_MODE = False

WEB_PORT = 8090

SELF_DB_THRESHOLD = -20
SELF_DB_VERY_LOUD = -6
SELF_ANGLE_DEAD = 3
SELF_ANGLE_DEAD_TIGHT = 1

GUNSHOT_ONSET_DB = -18

MAX_ANGLE_JUMP = 30
CONFIDENCE_THRESHOLD_LOW = 0.3
CONFIDENCE_THRESHOLD_HIGH = 0.7

MAX_SOURCES = 3
SOURCE_HOLD_SEC = 0.4


def angle_diff(a1, a2):
    diff = abs(a1 - a2)
    return min(diff, 360 - diff)


class AudioCaptureThread(threading.Thread):
    """音频捕获 + 处理线程"""
    
    def __init__(self, on_data_callback, sample_rate=SAMPLE_RATE):
        super().__init__(daemon=True)
        self.on_data = on_data_callback
        self.sample_rate = sample_rate
        self._running = False
        self._status_callback = None
        self._env_energy = 0.0
        self._last_event_time = 0.0
        self._smooth_angle = None
        self._last_angle = None
        self._angle_history = []
        self._peak_energy = 0.0
        self._last_sound_type = SOUND_TYPE_OTHER
        self._last_confidence = 0.0
        self._baseline = None
        self._noise_floor = 0.0
        self._noise_floor_history = []
        self._event_type_locked = False
        self._event_sound_type = SOUND_TYPE_OTHER
        self._direction_locked = False
        self._onset_total_e = 0.0
        self._clip_count = 0
        self._sources = []
        self._classifier_history = []
        self._footstep_count = 0
        self._last_footstep_time = 0.0
        self._is_behind = False

    def set_status_callback(self, cb):
        self._status_callback = cb
    
    def _status(self, text):
        if self._status_callback:
            self._status_callback(text)
    
    def stop(self):
        self._running = False
    
    def _update_noise_floor(self, energy):
        self._noise_floor_history.append(energy)
        if len(self._noise_floor_history) > 100:
            self._noise_floor_history.pop(0)
        self._noise_floor = np.percentile(self._noise_floor_history, 30)
    
    def _smooth_angle_filter(self, new_angle):
        if self._smooth_angle is None:
            self._smooth_angle = new_angle
        else:
            diff = angle_diff(self._smooth_angle, new_angle)
            if diff > MAX_ANGLE_JUMP:
                blend = 0.1
            else:
                blend = ANGLE_SMOOTH
            self._smooth_angle = self._smooth_angle * (1 - blend) + new_angle * blend
        
        self._angle_history.append(self._smooth_angle)
        if len(self._angle_history) > 5:
            self._angle_history.pop(0)
        
        return self._smooth_angle
    
    def _add_source(self, angle, energy, sound_type, confidence):
        angle_norm = angle % 360
        
        for src in self._sources:
            if angle_diff(src['angle'], angle_norm) < 25:
                src['energy'] = max(src['energy'], energy)
                src['last_update'] = time.time()
                src['confidence'] = max(src['confidence'], confidence)
                return
        
        if len(self._sources) < MAX_SOURCES:
            self._sources.append({
                'angle': angle_norm,
                'energy': energy,
                'sound_type': sound_type,
                'confidence': confidence,
                'last_update': time.time(),
                'hold_time': HOLD_SEC_GUNSHOT if sound_type == SOUND_TYPE_GUNSHOT else HOLD_SEC_FOOTSTEP,
            })
    
    def _cleanup_sources(self, now):
        self._sources = [src for src in self._sources 
                        if now - src['last_update'] < src['hold_time']]
    
    def _make_display_data(self, analysis, classification, now):
        if analysis['has_sound']:
            inst = analysis['total_energy']
            if inst >= self._env_energy:
                self._env_energy = inst
            else:
                self._env_energy = self._env_energy * ENV_RELEASE + inst * (1 - ENV_RELEASE)
            self._last_event_time = now

            conf = analysis['confidence']
            new_angle = analysis['angle']
            
            front_back = analysis.get('front_back', 0.0)
            
            if front_back < -0.3:
                new_angle += 180
                self._is_behind = True
            else:
                self._is_behind = False
            
            if not self._direction_locked:
                if self._last_angle is not None:
                    diff = angle_diff(self._last_angle, new_angle)
                    if diff > MAX_ANGLE_JUMP and conf < CONFIDENCE_THRESHOLD_HIGH:
                        new_angle = self._last_angle
                
                self._smooth_angle = self._smooth_angle_filter(new_angle)
                self._last_angle = self._smooth_angle
                self._direction_locked = True

            self._last_confidence = conf
            self._last_sound_type = self._event_sound_type
            
            self._add_source(self._smooth_angle, self._env_energy, 
                           self._event_sound_type, conf)
        else:
            hold_sec = HOLD_SEC_GUNSHOT if self._event_sound_type == SOUND_TYPE_GUNSHOT else HOLD_SEC_FOOTSTEP
            if now - self._last_event_time > hold_sec:
                self._env_energy = 0.0
                self._peak_energy = 0.0
                self._smooth_angle = None
                self._direction_locked = False
                self._event_type_locked = False
                return CompassData()
            self._env_energy *= ENV_RELEASE

        self._cleanup_sources(now)
        
        e = self._env_energy
        if e < 1e-10 or self._smooth_angle is None:
            return CompassData()

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
        data.front_back = self._is_behind
        return data

    def run(self):
        self._running = True
        
        try:
            import soundcard as sc
        except ImportError:
            self._status('错误: soundcard 库未安装')
            return

        try:
            all_mics = sc.all_microphones(include_loopback=True)
            loopback = None

            try:
                default_speaker_name = sc.default_speaker().name
                for m in all_mics:
                    if m.isloopback and m.name == default_speaker_name:
                        loopback = m
                        break
            except Exception:
                pass

            if loopback is None:
                for m in all_mics:
                    if m.isloopback:
                        loopback = m
                        break

            if loopback is None:
                self._status('错误: 未找到 WASAPI Loopback 设备')
                return

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

                        analysis = analyze_audio_block(data, method='weighted')

                        total_e = analysis['total_energy']
                        total_db = 20 * np.log10(total_e + 1e-10)
                        
                        self._update_noise_floor(total_e)
                        
                        if self._baseline is None:
                            self._baseline = total_e
                        
                        self._baseline = self._baseline * BASELINE_DECAY + total_e * (1 - BASELINE_DECAY)
                        
                        noise_gate_db = 20 * np.log10(self._noise_floor * 2 + 1e-10)
                        effective_floor = max(ONSET_FLOOR_DB, noise_gate_db)
                        
                        if SIMPLE_MODE:
                            is_onset = (total_db > LOUD_ALWAYS_DB) and (total_db > effective_floor)
                        else:
                            is_onset = ((total_e > self._baseline * ONSET_RATIO) or (total_db > LOUD_ALWAYS_DB)) \
                                       and (total_db > effective_floor)
                        
                        if is_onset:
                            analysis['has_sound'] = True
                            peak = float(np.max(np.abs(data))) if data.size > 0 else 0.0
                            
                            if peak > CLIP_THRESHOLD:
                                self._clip_count += 1
                                if self._smooth_angle is not None:
                                    pass
                                else:
                                    analysis['angle'] = 0.0
                                    self._direction_locked = False
                            elif peak > CLIP_WARNING_THRESHOLD:
                                self._direction_locked = False
                            else:
                                self._direction_locked = False
                            
                            self._event_type_locked = False
                            self._onset_total_e = total_e
                        elif self._env_energy > self._baseline * 1.5:
                            analysis['has_sound'] = True
                        else:
                            analysis['has_sound'] = False

                        if analysis['has_sound']:
                            total_db = 20 * np.log10(analysis['total_energy'] + 1e-10)
                            a = analysis['angle']
                            while a > 180:
                                a -= 360
                            while a <= -180:
                                a += 360
                            
                            if total_db > SELF_DB_VERY_LOUD and abs(a) <= SELF_ANGLE_DEAD:
                                analysis['has_sound'] = False
                            elif total_db > SELF_DB_THRESHOLD and abs(a) <= SELF_ANGLE_DEAD_TIGHT:
                                analysis['has_sound'] = False

                        if analysis['has_sound']:
                            if is_onset:
                                cls = classify_sound(data)
                                self._classifier_history.append(cls)
                                if len(self._classifier_history) > 5:
                                    self._classifier_history.pop(0)
                                
                                gun_count = sum(1 for c in self._classifier_history if c['type'] == 'gunshot' and c['confidence'] > 0.5)
                                foot_count = sum(1 for c in self._classifier_history if c['type'] == 'footstep' and c['confidence'] > 0.5)
                                other_count = len(self._classifier_history) - gun_count - foot_count
                                
                                current_time = time.time()
                                if current_time - self._last_footstep_time < 0.5:
                                    self._footstep_count += 1
                                else:
                                    self._footstep_count = 1
                                self._last_footstep_time = current_time
                                
                                if total_db > GUNSHOT_ONSET_DB:
                                    self._event_sound_type = SOUND_TYPE_GUNSHOT
                                    self._footstep_count = 0
                                elif total_db > -22 and gun_count >= 2:
                                    self._event_sound_type = SOUND_TYPE_GUNSHOT
                                elif self._footstep_count >= 2:
                                    self._event_sound_type = SOUND_TYPE_FOOTSTEP
                                elif foot_count >= 3:
                                    self._event_sound_type = SOUND_TYPE_FOOTSTEP
                                elif gun_count > foot_count:
                                    self._event_sound_type = SOUND_TYPE_GUNSHOT
                                elif foot_count >= gun_count:
                                    self._event_sound_type = SOUND_TYPE_FOOTSTEP
                                elif total_db > -22:
                                    self._event_sound_type = SOUND_TYPE_GUNSHOT
                                else:
                                    self._event_sound_type = SOUND_TYPE_FOOTSTEP
                                self._event_type_locked = True
                            
                            classification = {
                                'type': 'gunshot' if self._event_sound_type == SOUND_TYPE_GUNSHOT else 'footstep',
                                'confidence': 0.9, 'features': {},
                            }
                        else:
                            self._classifier_history = []
                            classification = {'type': 'silence', 'confidence': 1.0, 'features': {}}

                        now = time.time()
                        compass_data = self._make_display_data(analysis, classification, now)

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
    try:
        from serial.tools import list_ports
    except ImportError:
        return None

    ports = list(list_ports.comports())

    for p in ports:
        desc = (p.description or '').lower()
        if 'ch343' in desc or 'usb-serial ch' in desc or 'usb 串行' in desc:
            return p.device

    for p in ports:
        hwid = (p.hwid or '').upper()
        if 'VID:PID=1A86' in hwid or 'VID_1A86' in hwid:
            return p.device
        if 'VID:PID=303A' in hwid or 'VID_303A' in hwid:
            return p.device

    return None


class SerialSender:
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

    status_parts = []
    port = find_compass_port()
    if port:
        if serial_sender.connect(port):
            status_parts.append(f'圆屏 {port}')
        else:
            status_parts.append('无圆屏')
    else:
        status_parts.append('无圆屏')

    web_server = WebRadarServer(port=WEB_PORT)
    web_addr = ''
    if web_server.start():
        ip = get_local_ip()
        web_addr = f'Web http://{ip}:{WEB_PORT}'
        status_parts.append(web_addr)

    app.set_status(' | '.join(status_parts))

    def status_callback(text):
        if web_addr:
            app.set_status(f'{text} | {web_addr}')
        else:
            app.set_status(text)

    def on_data(data: CompassData):
        app.set_data(data)
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