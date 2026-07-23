"""播放8声道测试音频，同时捕获验证"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding='utf-8')

import numpy as np
import wave
import soundcard as sc
import threading
import time

SAMPLE_RATE = 48000


def main():
    # 用 wave 模块读取 WAV
    with wave.open('test_71_audio.wav', 'rb') as wf:
        sr = wf.getframerate()
        n_channels = wf.getnchannels()
        n_frames = wf.getnframes()
        data_bytes = wf.readframes(n_frames)
        data = np.frombuffer(data_bytes, dtype=np.int16).reshape(-1, n_channels)
        data = data.astype(np.float32) / 32768.0

    print(f'测试音频: {data.shape}, {sr}Hz, {n_channels} 声道')

    # 找 Voicemeeter 设备（选声道最多的渲染端点，确保命中 7.1 那个）
    vm_speakers = [s for s in sc.all_speakers() if 'voicemeeter' in s.name.lower()]
    vm_speaker = max(vm_speakers, key=lambda s: s.channels) if vm_speakers else None

    if vm_speaker is None:
        print('未找到 Voicemeeter 设备，尝试默认扬声器')
        vm_speaker = sc.default_speaker()

    print(f'播放设备: {vm_speaker.name} ({vm_speaker.channels} 声道)')

    # 找 loopback 设备（锁定与播放同一个端点）
    mics = sc.all_microphones(include_loopback=True)
    vm_mic = None
    for m in mics:
        if m.isloopback and m.name == vm_speaker.name:
            vm_mic = m
            break

    if vm_mic is None:
        vm_loops = [m for m in mics if m.isloopback and 'voicemeeter' in m.name.lower()]
        if vm_loops:
            vm_mic = max(vm_loops, key=lambda m: m.channels)

    if vm_mic is None:
        for m in mics:
            if m.isloopback:
                vm_mic = m
                break

    if vm_mic is None:
        print('未找到 loopback 设备')
        return

    print(f'捕获设备: {vm_mic.name} ({vm_mic.channels} 声道)')

    # 如果声道数不够，报警告
    if vm_mic.channels < 8:
        print(f'⚠️ 警告: 捕获设备只有 {vm_mic.channels} 声道，可能无法正确验证 7.1')

    channels = min(8, vm_mic.channels, vm_speaker.channels)

    # 播放
    print('播放测试音频（16秒）...')
    print('同时捕获声道能量...\n')

    recording = []
    recording_lock = threading.Lock()

    def capture_loop():
        with vm_mic.recorder(samplerate=SAMPLE_RATE, channels=channels,
                             blocksize=int(SAMPLE_RATE * 0.05)) as rec:
            for i in range(160):  # 最多16秒
                try:
                    chunk = rec.record(int(SAMPLE_RATE * 0.1))
                    if chunk is not None and len(chunk) > 0:
                        with recording_lock:
                            recording.append(chunk.copy())
                except Exception as e:
                    print(f'捕获错误: {e}')
                    break

    # 开始捕获
    t = threading.Thread(target=capture_loop, daemon=True)
    t.start()

    # 播放（可能声道不匹配，截断或填充）
    try:
        if data.shape[1] > channels:
            data_play = data[:, :channels]
        elif data.shape[1] < channels:
            padding = np.zeros((data.shape[0], channels - data.shape[1]))
            data_play = np.hstack([data, padding])
        else:
            data_play = data

        vm_speaker.play(data_play.astype(np.float32), samplerate=SAMPLE_RATE)
    except Exception as e:
        print(f'播放错误: {e}')

    # 等待
    t.join(timeout=20)

    if not recording:
        print('没有捕获到数据')
        return

    # 合并所有块
    all_data = np.vstack(recording)
    print(f'\n捕获到 {len(all_data)} 样本，{all_data.shape[1]} 声道')
    print()

    # 分析每个声道的能量
    print('各声道能量:')
    channel_names = ['FL', 'FR', 'FC', 'LFE', 'RL', 'RR', 'SL', 'SR']
    max_energy = 0
    energies = []
    for i in range(all_data.shape[1]):
        e = np.sqrt(np.mean(all_data[:, i]**2))
        energies.append(e)
        if e > max_energy:
            max_energy = e

    for i, name in enumerate(channel_names):
        if i >= len(energies):
            break
        e = energies[i]
        db = 20 * np.log10(e + 1e-10)
        if max_energy > 0:
            bar_len = int((e / max_energy) * 30)
        else:
            bar_len = 0
        bar = '█' * bar_len + '░' * (30 - bar_len)
        print(f'  {name}: {bar} {db:6.1f}dB')

    # 找出能量最高的声道
    print()
    if max_energy > 0.001:
        top_idx = np.argmax(energies)
        print(f'能量最高: {channel_names[top_idx]} ({energies[top_idx]:.4f})')


if __name__ == '__main__':
    main()
