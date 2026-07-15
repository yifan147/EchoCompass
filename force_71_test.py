"""
测试：强制在 2 声道设备上请求 8 声道捕获
"""

import pyaudiowpatch as pyaudio
import numpy as np
import time

CHANNEL_NAMES = ["FL", "FR", "FC", "LFE", "RL", "RR", "SL", "SR"]

def main():
    print("=" * 60)
    print("强制 8 声道捕获测试")
    print("=" * 60)
    print()

    p = pyaudio.PyAudio()

    # 找 loopback 设备
    loopback_devices = []
    for i in range(p.get_device_count()):
        try:
            info = p.get_device_info_by_index(i)
            name = info.get('name', '')
            if 'Loopback' in name or 'loopback' in name.lower():
                loopback_devices.append((i, info))
                print(f"  [{i}] {name}")
                print(f"      maxInputChannels: {info['maxInputChannels']}")
                print(f"      defaultSampleRate: {info['defaultSampleRate']}")
        except Exception as e:
            pass

    print()

    if not loopback_devices:
        print("未找到 loopback 设备")
        p.terminate()
        return

    # 逐个尝试强制 8 声道
    for device_index, device_info in loopback_devices:
        name = device_info['name']
        print(f"尝试设备: {name}")
        print(f"  报告最大声道: {device_info['maxInputChannels']}")

        # 方案1: 强制请求 8 声道
        print("  → 方案1: 强制请求 8 声道...")
        try:
            stream = p.open(
                format=pyaudio.paFloat32,
                channels=8,
                rate=48000,
                input=True,
                input_device_index=device_index,
                frames_per_buffer=4800
            )
            print("  ✓ 成功！流已打开为 8 声道")

            # 读取几帧看看
            for i in range(5):
                data = stream.read(4800, exception_on_overflow=False)
                audio = np.frombuffer(data, dtype=np.float32).reshape(-1, 8)
                print(f"  帧 {i+1}: shape={audio.shape}")

            stream.stop_stream()
            stream.close()
            print()
            continue

        except Exception as e:
            print(f"  ✗ 失败: {e}")

        # 方案2: 请求 7 声道
        print("  → 方案2: 请求 7 声道...")
        try:
            stream = p.open(
                format=pyaudio.paFloat32,
                channels=7,
                rate=48000,
                input=True,
                input_device_index=device_index,
                frames_per_buffer=4800
            )
            print("  ✓ 成功！7 声道")
            stream.stop_stream()
            stream.close()
            print()
            continue
        except Exception as e:
            print(f"  ✗ 失败: {e}")

        # 方案3: 用报告的最大声道数
        max_ch = device_info['maxInputChannels']
        print(f"  → 方案3: 请求 {max_ch} 声道（设备报告的最大值）...")
        try:
            stream = p.open(
                format=pyaudio.paFloat32,
                channels=max_ch,
                rate=48000,
                input=True,
                input_device_index=device_index,
                frames_per_buffer=4800
            )
            print(f"  ✓ 成功！{max_ch} 声道")
            stream.stop_stream()
            stream.close()
            print()
        except Exception as e:
            print(f"  ✗ 失败: {e}")
            print()

    p.terminate()
    print()
    print("=" * 60)
    print("结论:")
    print("如果所有方案都失败，说明该硬件确实不支持多声道。")
    print("需要安装虚拟 7.1 音频驱动（如 Voicemeeter Banana）来测试。")
    print("=" * 60)

if __name__ == "__main__":
    main()
