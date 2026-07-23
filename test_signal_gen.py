"""
Echo Compass - 8声道信号发生器测试
交互式：用键盘控制方向，播放脚步声/枪声
用于测试方向计算和分类器
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np
import soundcard as sc
import time
import threading

from echo_compass.signal_gen import generate_71_signal, generate_footstep_sequence, CHANNEL_NAMES
from echo_compass.direction import analyze_audio_block, channel_energies
from echo_compass.classifier import classify_sound


SAMPLE_RATE = 48000


def print_status(angle, distance, sound_type):
    """打印当前状态"""
    os.system('cls' if os.name == 'nt' else 'clear')
    print("=" * 70)
    print("Echo Compass - 8声道信号发生器（测试用）")
    print("=" * 70)
    print()
    print(f"  方向: {angle:6.1f}°  (0°=正前方, 顺时针)")
    print(f"  距离: {distance*100:3.0f}%  (0%=最近, 100%=最远)")
    print(f"  类型: {sound_type}")
    print()
    print("  控制:")
    print("    A/D - 左右转 15°")
    print("    W/S - 前后移动")
    print("    Q/E - 距离 +/-10%")
    print("    空格 - 播放一声 (按一下响一下)")
    print("    F   - 切换声音类型 (footstep/gunshot)")
    print("    R   - 重置方向到 0°")
    print("    ESC - 退出")
    print("=" * 70)


class AudioPlayer:
    """实时播放 8 声道音频的播放器"""
    
    def __init__(self, sample_rate=SAMPLE_RATE, channels=8):
        self.sample_rate = sample_rate
        self.channels = channels
        
        # 找到默认扬声器
        speaker = sc.default_speaker()
        print(f"使用扬声器: {speaker.name}")
        
        self.speaker = speaker
        self.player = None
        self._buffer = np.zeros((0, channels), dtype=np.float32)
        self._lock = threading.Lock()
        self._running = False
        self._thread = None
    
    def start(self):
        """启动播放"""
        self.player = self.speaker.player(
            samplerate=self.sample_rate,
            channels=self.channels,
            blocksize=int(self.sample_rate * 0.05),  # 50ms
        )
        self.player.__enter__()
        self._running = True
        self._thread = threading.Thread(target=self._play_loop, daemon=True)
        self._thread.start()
    
    def stop(self):
        """停止播放"""
        self._running = False
        if self._thread:
            self._thread.join(timeout=1.0)
        if self.player:
            self.player.__exit__(None, None, None)
    
    def queue_audio(self, audio_data):
        """把音频数据加入播放队列"""
        with self._lock:
            if self._buffer.shape[0] == 0:
                self._buffer = audio_data.astype(np.float32)
            else:
                self._buffer = np.vstack([self._buffer, audio_data.astype(np.float32)])
    
    def _play_loop(self):
        """播放循环"""
        while self._running:
            with self._lock:
                if self._buffer.shape[0] > 0:
                    # 取 10ms 的数据
                    n = min(int(self.sample_rate * 0.01), self._buffer.shape[0])
                    chunk = self._buffer[:n]
                    self._buffer = self._buffer[n:]
                else:
                    chunk = np.zeros((int(self.sample_rate * 0.01), self.channels), dtype=np.float32)
            
            self.player.play(chunk)
    
    def is_playing(self):
        """检查是否还有缓冲数据在播放"""
        with self._lock:
            return self._buffer.shape[0] > 0


def main():
    print("正在初始化音频播放器...")
    player = AudioPlayer()
    player.start()
    
    angle = 0.0
    distance = 0.3
    sound_type = 'footstep'
    
    try:
        import msvcrt
        
        print_status(angle, distance, sound_type)
        
        while True:
            if msvcrt.kbhit():
                key = msvcrt.getch()
                
                if key == b'\x1b':  # ESC
                    break
                
                elif key == b'a' or key == b'A':
                    angle -= 15
                    angle = ((angle + 180) % 360) - 180
                    print_status(angle, distance, sound_type)
                
                elif key == b'd' or key == b'D':
                    angle += 15
                    angle = ((angle + 180) % 360) - 180
                    print_status(angle, distance, sound_type)
                
                elif key == b'w' or key == b'W':
                    # 向前：减小距离
                    distance = max(0.0, distance - 0.1)
                    print_status(angle, distance, sound_type)
                
                elif key == b's' or key == b'S':
                    # 向后：增大距离
                    distance = min(1.0, distance + 0.1)
                    print_status(angle, distance, sound_type)
                
                elif key == b'q' or key == b'Q':
                    distance = max(0.0, distance - 0.1)
                    print_status(angle, distance, sound_type)
                
                elif key == b'e' or key == b'E':
                    distance = min(1.0, distance + 0.1)
                    print_status(angle, distance, sound_type)
                
                elif key == b' ':
                    # 播放一声
                    signal = generate_71_signal(sound_type, angle, distance)
                    player.queue_audio(signal)
                    print_status(angle, distance, sound_type)
                    print(f"\n  ▶ 播放 {sound_type} (角度 {angle:.1f}°, 距离 {distance*100:.0f}%)")
                
                elif key == b'f' or key == b'F':
                    sound_type = 'gunshot' if sound_type == 'footstep' else 'footstep'
                    print_status(angle, distance, sound_type)
                
                elif key == b'r' or key == b'R':
                    angle = 0.0
                    print_status(angle, distance, sound_type)
            
            time.sleep(0.01)
    
    except ImportError:
        # 非 Windows 系统
        print("提示: 此脚本需要 Windows 的 msvcrt 模块")
        print("播放一声 0° 的测试音...")
        signal = generate_71_signal('footstep', 0, 0.3)
        player.queue_audio(signal)
        time.sleep(1.0)
    
    finally:
        print("\n正在关闭...")
        player.stop()


if __name__ == "__main__":
    main()
