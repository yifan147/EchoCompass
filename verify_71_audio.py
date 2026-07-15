"""
Echo Compass 音频捕获验证脚本
验证 Windows 7.1 声道捕获能力
"""

import sys
import numpy as np
import time

SAMPLE_RATE = 48000

CHANNEL_NAMES = [
    "FL", "FR", "FC", "LFE",
    "RL", "RR", "SL", "SR"
]

CHANNEL_FULL_NAMES = [
    "前左 (FL)",
    "前右 (FR)",
    "中置 (FC)",
    "低音 (LFE)",
    "后左 (RL)",
    "后右 (RR)",
    "侧左 (SL)",
    "侧右 (SR)"
]

def rms_db(energy):
    if energy <= 0:
        return -100
    db = 20 * np.log10(energy)
    return max(-60, min(db, 0))

def draw_bar(db, width=18):
    if db < -60:
        return ' ' * width
    ratio = (db + 60) / 60
    filled = int(ratio * width)
    return '█' * filled + '░' * (width - filled)

def main_soundcard():
    import soundcard as sc

    print("使用 soundcard 库 (WASAPI Loopback)")
    print("=" * 60)
    print()

    speaker = sc.default_speaker()
    print(f"默认扬声器: {speaker.name}")
    print()

    print("查找 WASAPI Loopback 设备...")
    all_mics = sc.all_microphones(include_loopback=True)

    loopback_devices = [m for m in all_mics if m.isloopback]
    print(f"找到 {len(loopback_devices)} 个 loopback 设备:")
    for i, m in enumerate(loopback_devices):
        print(f"  [{i}] {m.name} ({m.channels} 声道)")
    print()

    if not loopback_devices:
        print("错误: 未找到任何 loopback 设备")
        return False

    # 选择默认扬声器对应的 loopback 设备
    selected = None
    speaker_prefix = speaker.name.split('(')[0].strip()
    for m in loopback_devices:
        if speaker_prefix in m.name:
            selected = m
            break

    if selected is None:
        selected = loopback_devices[0]
        print(f"提示: 无法匹配默认扬声器，使用第一个 loopback 设备")

    print(f"使用设备: {selected.name}")
    print(f"当前声道数: {selected.channels}")
    print()

    if selected.channels < 8:
        print("⚠️  警告: 当前设备只支持", selected.channels, "声道（期望 8 声道）")
        print()
        print("请按以下步骤配置 Windows 7.1 输出:")
        print("  1. 右键任务栏音量图标 → 声音设置")
        print("  2. 找到你的输出设备 → 设备属性")
        print("  3. 配置声道 → 选择 7.1 环绕")
        print("  4. 关闭空间音效 (Windows Sonic / Dolby Atmos)")
        print()
        print("注意: 即使没有 7.1 音箱，也可以虚拟输出 7.1 声道供 loopback 捕获")
        print()

    # 尝试以 8 声道录音
    target_channels = 8
    blocksize = int(SAMPLE_RATE * 0.1)

    print(f"尝试创建录音器: {SAMPLE_RATE}Hz, {target_channels} 声道, {blocksize} 样本/块")
    print()

    try:
        # soundcard 正确 API: 设备对象.recorder()
        with selected.recorder(samplerate=SAMPLE_RATE, channels=target_channels, blocksize=blocksize) as rec:
            print("✓ 录音器创建成功！")
            print(f"  设备: {selected.name}")
            print(f"  采样率: {SAMPLE_RATE} Hz")
            print(f"  目标声道数: {target_channels}")
            print()
            print("开始捕获！播放 7.1 测试音频观察各声道能量...")
            print("按 Ctrl+C 停止")
            print()

            iteration = 0
            last_time = time.time()
            warned_2ch = False

            while True:
                try:
                    data = rec.record(int(SAMPLE_RATE * 0.1))
                    iteration += 1

                    if data is None or data.size == 0:
                        time.sleep(0.05)
                        continue

                    if len(data.shape) == 1:
                        nchannels = 1
                    else:
                        nchannels = data.shape[1]

                    current_time = time.time()
                    elapsed = current_time - last_time

                    if iteration % 10 == 1:
                        print()
                        print("-" * 72)
                        print(f"{'声道':<6} | {'能量条':<20} | {'RMS':<12} | {'dB':<8}")
                        print("-" * 72)

                    for ch in range(min(nchannels, 8)):
                        channel_data = data[:, ch]
                        energy = np.sqrt(np.mean(channel_data**2))
                        db = rms_db(energy)
                        bar = draw_bar(db, 20)
                        print(f"{CHANNEL_NAMES[ch]:<6} | {bar} | {energy:<12.6f} | {db:<8.1f}")

                    print("-" * 72)

                    if nchannels < 8 and not warned_2ch and iteration > 5:
                        warned_2ch = True
                        if nchannels == 2:
                            print()
                            print("⚠️  警告: 实际只捕获到 2 声道！")
                            print("  → Windows 输出可能不是 7.1 配置")
                            print("  → 请关闭空间音效")
                            print()
                        else:
                            print(f"⚠️  警告: 只检测到 {nchannels} 声道（期望 8 声道）")

                    time.sleep(max(0, 0.1 - elapsed))
                    last_time = time.time()

                except KeyboardInterrupt:
                    print("\n用户中断，退出。")
                    break
                except Exception as e:
                    print(f"捕获错误: {e}")
                    time.sleep(0.1)

            return True

    except Exception as e:
        print(f"录音器创建失败: {e}")
        print()
        return False

def main_pyaudiowpatch():
    import pyaudiowpatch as pyaudio

    print()
    print("使用 pyaudiowpatch 库 (WASAPI Loopback)")
    print("=" * 60)
    print()

    p = pyaudio.PyAudio()

    print("查找 WASAPI loopback 设备...")
    loopback_devices = []

    for i in range(p.get_device_count()):
        try:
            info = p.get_device_info_by_index(i)
            name = info.get('name', '')
            if 'Loopback' in name or 'loopback' in name.lower():
                loopback_devices.append((i, info))
                print(f"  [{i}] {name} ({info['maxInputChannels']} 声道)")
        except:
            pass

    if not loopback_devices:
        print("未找到 WASAPI loopback 设备")
        p.terminate()
        return False

    print()

    # 使用第一个设备
    device_index, device_info = loopback_devices[0]
    channels = min(8, int(device_info['maxInputChannels']))

    print(f"使用设备: {device_info['name']}")
    print(f"最大输入声道: {device_info['maxInputChannels']}")
    print(f"采样率: {device_info['defaultSampleRate']}")

    if channels < 8:
        print(f"⚠️  警告: 设备最大支持 {channels} 声道")
        print("  → 请将 Windows 声音输出配置为 7.1 声道")
        print("  → 关闭空间音效")
    print()

    try:
        stream = p.open(
            format=pyaudio.paFloat32,
            channels=8,
            rate=int(device_info['defaultSampleRate']),
            input=True,
            input_device_index=device_index,
            frames_per_buffer=int(device_info['defaultSampleRate']) // 10
        )

        print("✓ 流打开成功！")
        print("开始捕获！播放 7.1 测试音频观察各声道能量...")
        print("按 Ctrl+C 停止")
        print()

        iteration = 0
        last_time = time.time()
        warned_2ch = False

        while True:
            try:
                data = stream.read(1024, exception_on_overflow=False)
                iteration += 1

                audio_data = np.frombuffer(data, dtype=np.float32)
                audio_data = audio_data.reshape(-1, 8)

                nchannels = audio_data.shape[1]

                current_time = time.time()
                elapsed = current_time - last_time

                if iteration % 10 == 1:
                    print()
                    print("-" * 72)
                    print(f"{'声道':<6} | {'能量条':<20} | {'RMS':<12} | {'dB':<8}")
                    print("-" * 72)

                for ch in range(min(nchannels, 8)):
                    channel_data = audio_data[:, ch]
                    energy = np.sqrt(np.mean(channel_data**2))
                    db = rms_db(energy)
                    bar = draw_bar(db, 20)
                    print(f"{CHANNEL_NAMES[ch]:<6} | {bar} | {energy:<12.6f} | {db:<8.1f}")

                print("-" * 72)

                if nchannels < 8 and not warned_2ch and iteration > 5:
                    warned_2ch = True
                    if nchannels == 2:
                        print()
                        print("⚠️  警告: 实际只捕获到 2 声道！")
                        print("  → Windows 输出可能不是 7.1 配置")
                        print("  → 请关闭空间音效")
                        print()

                time.sleep(max(0, 0.1 - elapsed))
                last_time = time.time()

            except KeyboardInterrupt:
                print("\n用户中断，退出。")
                break
            except Exception as e:
                print(f"读取错误: {e}")
                time.sleep(0.1)

        stream.stop_stream()
        stream.close()
        p.terminate()
        return True

    except Exception as e:
        print(f"流打开失败: {e}")
        p.terminate()
        return False

def main():
    print("=" * 60)
    print("Echo Compass - 7.1 声道捕获验证脚本")
    print("=" * 60)
    print()

    success = False

    # 先试 soundcard
    try:
        success = main_soundcard()
    except ImportError:
        print("soundcard 未安装")
    except Exception as e:
        print(f"soundcard 出错: {e}")

    if success:
        return

    # soundcard 失败，试 pyaudiowpatch
    print()
    print("尝试 pyaudiowpatch...")
    try:
        success = main_pyaudiowpatch()
    except ImportError:
        print("pyaudiowpatch 未安装")
    except Exception as e:
        print(f"pyaudiowpatch 出错: {e}")

    if not success:
        print()
        print("错误: 无法创建音频捕获")
        print("请确保:")
        print("  1. 已安装 soundcard 或 pyaudiowpatch 库")
        print("  2. Windows 音频服务正常运行")
        sys.exit(1)

if __name__ == "__main__":
    main()
