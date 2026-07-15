"""
Echo Compass - 端到端测试
信号发生器(播放) → 系统输出 → WASAPI loopback(捕获) → 算法计算 → 显示结果

用于验证：
1. 方向计算是否准确
2. 距离估计是否合理
3. 声音分类是否正确
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np
import time
import threading
import soundcard as sc

from echo_compass.signal_gen import generate_71_signal, generate_footstep_sequence, CHANNEL_NAMES
from echo_compass.direction import analyze_audio_block, channel_energies
from echo_compass.classifier import classify_sound


SAMPLE_RATE = 48000


def draw_compass(angle, distance, sound_type, has_sound, width=40):
    """画一个 ASCII 罗盘"""
    
    # 罗盘半径
    radius = width // 2 - 2
    
    # 初始化画布
    canvas = [[' ' for _ in range(width)] for _ in range(width)]
    
    # 画圆
    cx, cy = width // 2, width // 2
    for y in range(width):
        for x in range(width):
            dx = x - cx
            dy = y - cy
            dist = int(np.sqrt(dx*dx + dy*dy))
            if dist == radius:
                canvas[y][x] = '·'
            elif dist == radius // 2:
                canvas[y][x] = '·'
    
    # 画正前方标记
    canvas[0][cx] = '▲'
    canvas[cy][0] = '◀'
    canvas[cy][width-1] = '▶'
    canvas[width-1][cx] = '▼'
    
    # 画中心点
    canvas[cy][cx] = '○'
    
    if has_sound:
        # 计算点的位置
        # 角度 0°=正前方（上），顺时针
        rad = np.radians(90 - angle)  # 转换为标准数学角度
        # 距离映射：distance 0~1 → 半径 0~radius
        r = int(radius * (1.0 - distance * 0.8))  # 最近的在半径80%处
        x = int(cx + r * np.cos(rad))
        y = int(cy - r * np.sin(rad))
        
        # 确保在范围内
        x = max(0, min(width-1, x))
        y = max(0, min(width-1, y))
        
        # 画点
        icon = {'footstep': '●', 'gunshot': '✦', 'other': '○'}.get(sound_type, '●')
        canvas[y][x] = icon
    
    return [''.join(row) for row in canvas]


def run_test(test_cases, capture_device_name=None):
    """
    运行一组测试用例
    
    test_cases: list of dict {angle, distance, type, label}
    """
    
    print("=" * 70)
    print("Echo Compass - 端到端方向/距离/分类测试")
    print("=" * 70)
    print()
    
    # 找到 loopback 设备
    all_mics = sc.all_microphones(include_loopback=True)
    loopback = None
    
    if capture_device_name:
        for m in all_mics:
            if capture_device_name.lower() in m.name.lower():
                loopback = m
                break
    
    if loopback is None:
        # 找声道数最多的 loopback 设备
        loopbacks = [m for m in all_mics if m.isloopback]
        if loopbacks:
            loopback = max(loopbacks, key=lambda m: m.channels)
    
    if loopback is None:
        print("错误: 未找到 loopback 设备")
        return
    
    print(f"捕获设备: {loopback.name}")
    print(f"声道数: {loopback.channels}")
    print()
    
    # 找到扬声器（优先用声道数最多的）
    all_speakers = sc.all_speakers()
    speaker = max(all_speakers, key=lambda s: s.channels)
    print(f"播放设备: {speaker.name}")
    print(f"播放声道数: {speaker.channels}")
    print()
    
    if loopback.channels < 8:
        print("⚠️  警告: 捕获设备只有", loopback.channels, "声道，方向计算可能不准确")
        print()
    
    channels = min(8, loopback.channels)
    
    print("开始测试...")
    print()
    
    results = []
    
    # 打开录音器
    with loopback.recorder(samplerate=SAMPLE_RATE, channels=channels, blocksize=int(SAMPLE_RATE*0.01)) as rec:
        # 打开播放器
        with speaker.player(samplerate=SAMPLE_RATE, channels=channels, blocksize=int(SAMPLE_RATE*0.01)) as player:
            
            for i, test in enumerate(test_cases):
                angle = test['angle']
                distance = test.get('distance', 0.3)
                sound_type = test.get('type', 'footstep')
                label = test.get('label', f'测试{i+1}')
                
                print(f"--- 测试 {i+1}: {label} ---")
                print(f"  期望: 角度={angle:6.1f}°, 距离={distance*100:3.0f}%, 类型={sound_type}")
                
                # 生成测试信号
                signal = generate_71_signal(sound_type, angle, distance)
                
                # 先清空缓冲区（读掉旧数据）
                for _ in range(5):
                    _ = rec.record(int(SAMPLE_RATE * 0.02))
                    time.sleep(0.01)
                
                # 开始播放
                play_thread = threading.Thread(target=lambda: player.play(signal), daemon=True)
                play_thread.start()
                
                # 等待一小段延迟（声音从播放到捕获需要一点时间）
                time.sleep(0.05)
                
                # 捕获
                captured_data = []
                for _ in range(20):  # 最多 200ms
                    chunk = rec.record(int(SAMPLE_RATE * 0.01))
                    captured_data.append(chunk)
                    # 如果总能量够大了，可以提前停止
                    if len(captured_data) > 5:
                        all_data = np.vstack(captured_data)
                        e = np.sqrt(np.mean(all_data**2))
                        if e > 0.01:
                            break
                
                play_thread.join(timeout=1.0)
                
                if not captured_data:
                    print("  ✗ 未捕获到音频")
                    results.append(None)
                    continue
                
                all_captured = np.vstack(captured_data)
                
                # 分析
                analysis = analyze_audio_block(all_captured)
                classification = classify_sound(all_captured)
                
                # 显示结果
                print(f"  结果: 角度={analysis['angle']:6.1f}°, 距离={analysis['distance']*100:3.0f}%, "
                      f"类型={classification['type']} (置信度={classification['confidence']:.2f})")
                
                if analysis['has_sound']:
                    angle_error = abs(analysis['angle'] - angle)
                    if angle_error > 180:
                        angle_error = 360 - angle_error
                    print(f"  误差: 角度={angle_error:.1f}°, 距离={abs(analysis['distance']-distance)*100:.0f}%")
                
                # 画罗盘
                compass = draw_compass(
                    analysis['angle'],
                    analysis['distance'],
                    classification['type'],
                    analysis['has_sound']
                )
                for line in compass:
                    print(f"  {line}")
                
                results.append({
                    'expected': test,
                    'got': analysis,
                    'classification': classification,
                })
                
                print()
                time.sleep(0.3)
    
    # 汇总
    print("=" * 70)
    print("测试汇总")
    print("=" * 70)
    print(f"{'测试':<12} {'期望角度':>8} {'实际角度':>8} {'误差':>8} {'期望类型':>8} {'实际类型':>8}")
    print("-" * 70)
    
    for i, r in enumerate(results):
        if r is None:
            continue
        exp = r['expected']
        got = r['got']
        cls = r['classification']
        
        angle_error = abs(got['angle'] - exp['angle'])
        if angle_error > 180:
            angle_error = 360 - angle_error
        
        print(f"测试{i+1:<8} {exp['angle']:>7.1f}° {got['angle']:>7.1f}° {angle_error:>7.1f}° "
              f"{exp['type']:>8} {cls['type']:>8}")
    
    print()


def main():
    # 测试用例
    test_cases = [
        {'angle': 0,    'distance': 0.3, 'type': 'footstep', 'label': '正前方 脚步'},
        {'angle': 45,   'distance': 0.3, 'type': 'footstep', 'label': '右前方45° 脚步'},
        {'angle': 90,   'distance': 0.3, 'type': 'footstep', 'label': '正右方 脚步'},
        {'angle': 135,  'distance': 0.3, 'type': 'footstep', 'label': '右后方45° 脚步'},
        {'angle': 180,  'distance': 0.3, 'type': 'footstep', 'label': '正后方 脚步'},
        {'angle': -90,  'distance': 0.3, 'type': 'footstep', 'label': '正左方 脚步'},
        {'angle': 0,    'distance': 0.1, 'type': 'gunshot',  'label': '正前方 枪声(近)'},
        {'angle': 45,   'distance': 0.8, 'type': 'gunshot',  'label': '右前方45° 枪声(远)'},
    ]
    
    run_test(test_cases)


if __name__ == "__main__":
    main()
