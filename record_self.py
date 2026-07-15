"""
Echo Compass - 录制自身声音特征
用于采集"纯自己、无敌人"时的雷达数据，后续做"屏蔽自身声音"

用法:
    python record_self.py 干员A_步枪
    python record_self.py 干员B_手枪
    Ctrl+C 停止并落盘

输出: recordings/<标签>_<时间戳>.csv
"""

import sys
import os
import time
import signal
import csv
import numpy as np

from echo_compass.direction import analyze_audio_block
from echo_compass.classifier import classify_sound

SAMPLE_RATE = 48000
BLOCK_MS = 50
CHANNEL_NAMES = ["FL", "FR", "FC", "LFE", "RL", "RR", "SL", "SR"]


def find_loopback():
    """和 main.py 的 AudioCaptureThread.run 完全一样的设备选择逻辑"""
    import soundcard as sc

    all_mics = sc.all_microphones(include_loopback=True)
    loopback = None

    # 第一优先级：找默认播放设备对应的 loopback
    try:
        default_speaker_name = sc.default_speaker().name
        for m in all_mics:
            if m.isloopback and m.name == default_speaker_name:
                loopback = m
                break
    except Exception:
        pass

    # 第二优先级：声道最多的 Voicemeeter loopback（兜底）
    if loopback is None:
        vm_loops = [m for m in all_mics if m.isloopback and 'voicemeeter' in m.name.lower()]
        if vm_loops:
            loopback = max(vm_loops, key=lambda m: m.channels)
        else:
            for m in all_mics:
                if m.isloopback:
                    loopback = m
                    break

    if loopback is None:
        print('错误: 未找到 WASAPI Loopback 设备')
        sys.exit(1)

    return loopback


def main():
    if len(sys.argv) < 2:
        print('用法: python record_self.py <标签>')
        print('示例: python record_self.py 干员A_步枪')
        sys.exit(1)

    tag = sys.argv[1]

    # 创建输出目录
    out_dir = os.path.join(os.path.dirname(__file__), 'recordings')
    os.makedirs(out_dir, exist_ok=True)

    timestamp = time.strftime('%Y%m%d_%H%M%S')
    out_path = os.path.join(out_dir, f'{tag}_{timestamp}.csv')

    # 找 loopback 设备
    loopback = find_loopback()
    channels = min(8, loopback.channels)
    print(f'标签: {tag}')
    print(f'捕获: {loopback.name} ({channels} 声道)')
    print(f'输出: {out_path}')
    print('开始录制... 按 Ctrl+C 停止')
    print()

    blocksize = int(SAMPLE_RATE * BLOCK_MS / 1000)
    start_time = time.time()
    event_count = 0

    # CSV 表头
    header = (['time_s', 'type', 'angle', 'total_energy', 'db', 'confidence']
              + CHANNEL_NAMES
              + [f'{n}_norm' for n in CHANNEL_NAMES])

    # Ctrl+C 处理
    stop = False

    def _handler(sig, frame):
        nonlocal stop
        stop = True

    signal.signal(signal.SIGINT, _handler)

    # 边录边写：打开文件、写表头
    csv_file = open(out_path, 'w', newline='', encoding='utf-8')
    writer = csv.writer(csv_file)
    writer.writerow(header)
    csv_file.flush()

    flush_counter = 0

    try:
        with loopback.recorder(samplerate=SAMPLE_RATE, channels=channels,
                                blocksize=blocksize) as rec:
            while not stop:
                try:
                    data = rec.record(blocksize)
                    if data is None or data.size == 0:
                        time.sleep(0.01)
                        continue

                    analysis = analyze_audio_block(data, method='weighted')

                    if not analysis['has_sound']:
                        continue

                    classification = classify_sound(data)
                    rel_time = time.time() - start_time
                    total_e = analysis['total_energy']
                    db = 20 * np.log10(total_e + 1e-10)
                    cls_type = classification['type']
                    angle = analysis['angle']
                    conf = analysis['confidence']
                    energies = analysis['energies']

                    # 实时打印
                    event_count += 1
                    print(f'[{rel_time:7.2f}s] {cls_type:10s}  angle={angle:6.1f}°  '
                          f'dB={db:6.1f}  conf={conf:.2f}')

                    # 立即写一行 CSV
                    row = [f'{rel_time:.3f}', cls_type, f'{angle:.1f}',
                           f'{total_e:.6f}', f'{db:.2f}', f'{conf:.4f}']
                    # 绝对能量
                    for e in energies:
                        row.append(f'{e:.6f}')
                    # 归一化能量（每个声道 ÷ 总能量）
                    if total_e > 1e-10:
                        for e in energies:
                            row.append(f'{e / total_e:.4f}')
                    else:
                        for _ in energies:
                            row.append('0.0000')
                    writer.writerow(row)

                    # 每 20 行 flush 一次
                    flush_counter += 1
                    if flush_counter >= 20:
                        csv_file.flush()
                        flush_counter = 0

                except Exception as e:
                    print(f'捕获错误: {e}')
                    time.sleep(0.1)

    except Exception as e:
        print(f'录音器错误: {e}')
    finally:
        csv_file.close()

    print()
    print(f'录制结束，共 {event_count} 个事件，已保存到 {out_path}')


if __name__ == '__main__':
    main()
