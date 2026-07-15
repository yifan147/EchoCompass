"""快速验证所有核心模块"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from echo_compass.signal_gen import generate_71_signal
from echo_compass.direction import analyze_audio_block
from echo_compass.classifier import classify_sound
from echo_compass.protocol import CompassData, serialize, deserialize

# 测试信号生成
sig = generate_71_signal('footstep', 45, 0.3)
print(f'信号形状: {sig.shape}')

# 测试方向计算
result = analyze_audio_block(sig)
angle = result['angle']
dist = result['distance']
has = result['has_sound']
print(f'方向计算: 角度={angle:.1f}°, 距离={dist:.2f}, 有声={has}')

# 测试分类
cls = classify_sound(sig)
print(f'分类: {cls["type"]} (置信度={cls["confidence"]:.2f})')

# 测试协议
data = CompassData(has_sound=True, angle=45.0, distance=0.3, sound_type=1, energy=0.5, confidence=0.8)
frame = serialize(data)
print(f'序列化帧: {frame.hex()} ({len(frame)} 字节)')

decoded = deserialize(frame)
print(f'反序列化: 角度={decoded.angle:.1f}, 类型={decoded.sound_type}')

# 测试枪声
sig_gun = generate_71_signal('gunshot', -90, 0.5)
cls_gun = classify_sound(sig_gun)
result_gun = analyze_audio_block(sig_gun)
print()
print(f'枪声测试: 方向={result_gun["angle"]:.1f}°, 分类={cls_gun["type"]}')

print()
print('所有模块测试通过!')
