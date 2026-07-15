"""
生成 7.1 测试音频
8 声道，每声道轮流播放 500Hz 正弦波，每声道 2 秒
声道顺序: FL, FR, FC, LFE, RL, RR, SL, SR
"""

import numpy as np
import wave

SAMPLE_RATE = 48000
DURATION_PER_CHANNEL = 2.0  # 每声道持续时间（秒）
FREQUENCY = 500  # 正弦波频率
AMPLITUDE = 0.8  # 音量

CHANNEL_NAMES = [
    "FL (前左)",
    "FR (前右)",
    "FC (中置)",
    "LFE (低音)",
    "RL (后左)",
    "RR (后右)",
    "SL (侧左)",
    "SR (侧右)"
]

def generate_sine_wave(freq, duration, sample_rate, amplitude=0.8):
    """生成正弦波"""
    t = np.linspace(0, duration, int(sample_rate * duration), endpoint=False)
    wave_data = amplitude * np.sin(2 * np.pi * freq * t)
    return wave_data

def generate_71_test_audio(output_path):
    """生成 7.1 测试音频"""
    print(f"生成 7.1 测试音频: {output_path}")
    print(f"采样率: {SAMPLE_RATE} Hz")
    print(f"每声道时长: {DURATION_PER_CHANNEL} 秒")
    print(f"频率: {FREQUENCY} Hz")
    print()

    total_samples = int(SAMPLE_RATE * DURATION_PER_CHANNEL * 8)
    audio_data = np.zeros((total_samples, 8), dtype=np.float32)

    for ch in range(8):
        start_sample = int(ch * SAMPLE_RATE * DURATION_PER_CHANNEL)
        end_sample = int((ch + 1) * SAMPLE_RATE * DURATION_PER_CHANNEL)
        sine = generate_sine_wave(FREQUENCY, DURATION_PER_CHANNEL, SAMPLE_RATE, AMPLITUDE)
        audio_data[start_sample:end_sample, ch] = sine
        print(f"  声道 {ch+1} ({CHANNEL_NAMES[ch]}): {DURATION_PER_CHANNEL} 秒 @ {start_sample/SAMPLE_RATE:.1f}s")

    print()

    # 写入 WAV 文件
    # 转换为 16-bit PCM
    audio_int16 = (audio_data * 32767).astype(np.int16)

    with wave.open(output_path, 'w') as wf:
        wf.setnchannels(8)
        wf.setsampwidth(2)  # 16-bit
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(audio_int16.tobytes())

    print(f"✓ 已保存到: {output_path}")
    print(f"  总时长: {total_samples / SAMPLE_RATE:.1f} 秒")
    print(f"  文件大小: {total_samples * 8 * 2 / 1024 / 1024:.1f} MB")

if __name__ == "__main__":
    generate_71_test_audio(r"c:\Users\admin\Desktop\echo\test_71_audio.wav")
