/*
 * Echo Compass - ESP32-S3 圆屏固件
 * 1.28寸 GC9A01 圆屏 (240x240)
 *
 * 串口协议（与 echo_compass/protocol.py 一致）:
 *   8字节/帧: [0xAA][type][angle_hi][angle_lo][dist][energy][reserved][checksum]
 *   angle: 0~3600 (0.1度精度), 0=正前(屏幕上方), 顺时针
 *   type: 0=静音 1=脚步 2=枪声 3=其他
 *   distance: 0~100 (0=最近, 100=最远)
 *   energy: 0~255
 *   checksum: 前7字节 XOR
 *
 * 显示:
 *   - 外圈罗盘 + F/B/L/R + 中心点(自己)
 *   - 脚步: 蓝色圆点
 *   - 枪声: 红色带尖刺星形
 *   - 突发提醒: 1.5s以上无声后突然出现 → 整屏红光闪三下, 图标白色
 *   - 500ms无新帧 → 熄点
 */

#include <TFT_eSPI.h>

// ========== 常量 ==========
#define SCREEN_W       240
#define SCREEN_H       240
#define CENTER_X       120
#define CENTER_Y       120
#define COMPASS_R      100    // 罗盘外圈半径
#define CENTER_DOT_R   5      // 中心点半径
#define ICON_R         8      // 声音图标基础半径

// 串口协议
#define FRAME_HEADER   0xAA
#define FRAME_SIZE     8

#define TYPE_SILENCE   0
#define TYPE_FOOTSTEP  1
#define TYPE_GUNSHOT   2
#define TYPE_OTHER     3

// 颜色
#define COLOR_BLACK    0x0000
#define COLOR_WHITE    0xFFFF
#define COLOR_RED      0xF800
#define COLOR_BLUE     0x001F
#define COLOR_GRAY     0x4208
#define COLOR_DARK_GRAY 0x2104

// 时间参数 (毫秒)
#define TIMEOUT_HIDE   500    // 无新帧500ms熄点
#define SILENCE_THRESHOLD 1500 // 1.5s以上无声算"长时间静默"
#define FLASH_COUNT    3      // 闪三下
#define FLASH_DURATION 120    // 每闪一下120ms

// ========== 全局变量 ==========
TFT_eSPI tft = TFT_eSPI();
TFT_eSprite sprite = TFT_eSprite(&tft);

// 当前声音状态
bool    hasSound = false;
int     soundType = TYPE_SILENCE;
float   soundAngle = 0.0f;   // 度, 0=正上, 顺时针
float   soundDistance = 0.6f; // 0~1, 0=最近
int     soundEnergy = 0;

// 时间戳
uint32_t lastFrameTime = 0;
uint32_t lastSoundTime = 0;  // 最后一次有声音的时间
uint32_t silenceStart  = 0;  // 开始无声的时间

// 突发提醒状态
enum FlashState { FLASH_IDLE, FLASHING, FLASH_DONE_ONCE };
FlashState flashState = FLASH_IDLE;
int      flashCount = 0;
uint32_t flashStartTime = 0;
bool     wasSilent = true;   // 之前是否处于长时间静默

// 串口接收缓冲
uint8_t rxBuffer[FRAME_SIZE];
int     rxIndex = 0;

// ========== 函数声明 ==========
void drawCompassBackground(TFT_eSprite &sp);
void drawSoundIcon(TFT_eSprite &sp, float angleDeg, float distance, int type, uint16_t color);
void drawStarBurst(TFT_eSprite &sp, int cx, int cy, int r, uint16_t color);
void drawFullRed(TFT_eSprite &sp);
void angleToXY(float angleDeg, float distance, int &x, int &y);
void parseFrame(uint8_t *buf);
bool validateChecksum(uint8_t *buf);

// ========== 初始化 ==========
void setup() {
  Serial.begin(115200);

  // 初始化屏幕 (引脚已在 TFT_eSPI User_Setup.h 中配置)
  tft.init();
  tft.setRotation(2);  // 板子倒着装, 旋转180度
  tft.fillScreen(COLOR_BLACK);

  // 创建离屏 sprite
  sprite.setColorDepth(16);
  sprite.createSprite(SCREEN_W, SCREEN_H);

  // 画初始罗盘
  drawCompassBackground(sprite);
  sprite.pushSprite(0, 0);

  lastFrameTime = millis();
  lastSoundTime = millis();
  silenceStart  = millis();
}

// ========== 主循环 ==========
void loop() {
  // ---- 串口接收 ----
  while (Serial.available()) {
    uint8_t b = Serial.read();

    if (rxIndex == 0 && b != FRAME_HEADER) {
      continue;  // 跳过非帧头
    }

    rxBuffer[rxIndex++] = b;

    if (rxIndex >= FRAME_SIZE) {
      if (validateChecksum(rxBuffer)) {
        parseFrame(rxBuffer);
      }
      rxIndex = 0;
    }
  }

  // ---- 超时熄点 ----
  uint32_t now = millis();
  if (hasSound && (now - lastFrameTime > TIMEOUT_HIDE)) {
    hasSound = false;
    soundType = TYPE_SILENCE;
    drawCompassBackground(sprite);
    sprite.pushSprite(0, 0);
  }

  // ---- 突发提醒: 闪屏 ----
  if (flashState == FLASHING) {
    if (now - flashStartTime < FLASH_DURATION) {
      // 当前这一闪还在持续
    } else {
      flashCount++;
      if (flashCount >= FLASH_COUNT * 2) {
        // 三下闪完 (红-黑-红-黑-红-黑 = 6个阶段)
        flashState = FLASH_DONE_ONCE;
        // 闪完回到正常显示
        drawCompassBackground(sprite);
        if (hasSound) {
          drawSoundIcon(sprite, soundAngle, soundDistance, soundType, COLOR_WHITE);
        }
        sprite.pushSprite(0, 0);
      } else {
        // 切换红/黑
        if (flashCount % 2 == 0) {
          // 红色阶段
          drawFullRed(sprite);
          if (hasSound) {
            drawSoundIcon(sprite, soundAngle, soundDistance, soundType, COLOR_WHITE);
          }
        } else {
          // 黑色阶段
          drawCompassBackground(sprite);
          if (hasSound) {
            drawSoundIcon(sprite, soundAngle, soundDistance, soundType, COLOR_WHITE);
          }
        }
        sprite.pushSprite(0, 0);
        flashStartTime = now;
      }
    }
  }

  delay(10);
}

// ========== 画罗盘背景 ==========
void drawCompassBackground(TFT_eSprite &sp) {
  sp.fillSprite(COLOR_BLACK);

  // 外圈圆
  sp.drawCircle(CENTER_X, CENTER_Y, COMPASS_R, COLOR_GRAY);

  // 内圈装饰圆
  sp.drawCircle(CENTER_X, CENTER_Y, COMPASS_R - 15, COLOR_DARK_GRAY);

  // 方向字母 F/B/L/R
  sp.setTextColor(COLOR_GRAY);
  sp.setTextSize(1);
  sp.setTextDatum(MC_DATUM);

  // F (正上/正前)
  sp.drawString("F", CENTER_X, CENTER_Y - COMPASS_R + 14);
  // B (正下/正后)
  sp.drawString("B", CENTER_X, CENTER_Y + COMPASS_R - 14);
  // L (正左)
  sp.drawString("L", CENTER_X - COMPASS_R + 14, CENTER_Y);
  // R (正右)
  sp.drawString("R", CENTER_X + COMPASS_R - 14, CENTER_Y);

  // 十字参考线 (淡淡的)
  sp.drawLine(CENTER_X, CENTER_Y - COMPASS_R + 5, CENTER_X, CENTER_Y - 20, COLOR_DARK_GRAY);
  sp.drawLine(CENTER_X, CENTER_Y + 20, CENTER_X, CENTER_Y + COMPASS_R - 5, COLOR_DARK_GRAY);
  sp.drawLine(CENTER_X - COMPASS_R + 5, CENTER_Y, CENTER_X - 20, CENTER_Y, COLOR_DARK_GRAY);
  sp.drawLine(CENTER_X + 20, CENTER_Y, CENTER_X + COMPASS_R - 5, CENTER_Y, COLOR_DARK_GRAY);

  // 中心点 (自己)
  sp.fillCircle(CENTER_X, CENTER_Y, CENTER_DOT_R, COLOR_WHITE);
}

// ========== 画整屏红色 ==========
void drawFullRed(TFT_eSprite &sp) {
  sp.fillSprite(COLOR_RED);

  // 罗盘元素用暗色画在红底上
  sp.drawCircle(CENTER_X, CENTER_Y, COMPASS_R, COLOR_DARK_GRAY);
  sp.drawCircle(CENTER_X, CENTER_Y, COMPASS_R - 15, COLOR_BLACK);

  sp.setTextColor(COLOR_BLACK);
  sp.setTextSize(1);
  sp.setTextDatum(MC_DATUM);
  sp.drawString("F", CENTER_X, CENTER_Y - COMPASS_R + 14);
  sp.drawString("B", CENTER_X, CENTER_Y + COMPASS_R - 14);
  sp.drawString("L", CENTER_X - COMPASS_R + 14, CENTER_Y);
  sp.drawString("R", CENTER_X + COMPASS_R - 14, CENTER_Y);

  sp.fillCircle(CENTER_X, CENTER_Y, CENTER_DOT_R, COLOR_BLACK);
}

// ========== 角度+距离 → 屏幕坐标 ==========
// angleDeg: 0=正上, 顺时针
// distance: 0=最近(中心), 1=最远(外圈)
void angleToXY(float angleDeg, float distance, int &x, int &y) {
  // 转成弧度, 0度=正上(屏幕-Y方向), 顺时针
  float rad = (angleDeg - 90.0f) * PI / 180.0f;
  // distance 0.1=靠近中心, 0.9=靠近外圈
  float r = COMPASS_R * (0.1f + distance * 0.8f);
  x = CENTER_X + (int)(r * cos(rad));
  y = CENTER_Y + (int)(r * sin(rad));
}

// ========== 画声音图标 ==========
void drawSoundIcon(TFT_eSprite &sp, float angleDeg, float distance, int type, uint16_t color) {
  int x, y;
  angleToXY(angleDeg, distance, x, y);

  // 限制在罗盘范围内
  int dx = x - CENTER_X;
  int dy = y - CENTER_Y;
  float distFromCenter = sqrt(dx * dx + dy * dy);
  if (distFromCenter > COMPASS_R - ICON_R) {
    float scale = (COMPASS_R - ICON_R) / distFromCenter;
    x = CENTER_X + (int)(dx * scale);
    y = CENTER_Y + (int)(dy * scale);
  }

  if (type == TYPE_GUNSHOT) {
    // 枪声: 带尖刺的星形
    drawStarBurst(sp, x, y, ICON_R, color);
  } else {
    // 脚步/其他: 圆点
    sp.fillCircle(x, y, ICON_R, color);
  }
}

// ========== 画星形爆发 (枪声) ==========
void drawStarBurst(TFT_eSprite &sp, int cx, int cy, int r, uint16_t color) {
  // 中间实心圆
  int coreR = r / 2;
  if (coreR < 2) coreR = 2;
  sp.fillCircle(cx, cy, coreR, color);

  // 往外放射 7 条短线
  int numSpikes = 7;
  int spikeLen = r;  // 从中心到尖端的总长度
  int spikeWidth = 2;

  for (int i = 0; i < numSpikes; i++) {
    float angle = (float)i * 360.0f / numSpikes;
    float rad = angle * PI / 180.0f;

    int x1 = cx + (int)(coreR * cos(rad));
    int y1 = cy + (int)(coreR * sin(rad));
    int x2 = cx + (int)(spikeLen * cos(rad));
    int y2 = cy + (int)(spikeLen * sin(rad));

    // 画粗线 (用两条平行线模拟)
    sp.drawLine(x1, y1, x2, y2, color);

    // 偏移一点再画一条, 让线更粗
    int ox = (int)(spikeWidth * cos(rad + PI / 2));
    int oy = (int)(spikeWidth * sin(rad + PI / 2));
    sp.drawLine(x1 + ox, y1 + oy, x2 + ox, y2 + oy, color);
  }
}

// ========== 解析帧 ==========
void parseFrame(uint8_t *buf) {
  uint32_t now = millis();
  lastFrameTime = now;

  int type = buf[1];
  int angleInt = (buf[2] << 8) | buf[3];
  int distInt = buf[4];
  int energyInt = buf[5];

  float angle = angleInt / 10.0f;
  float distance = distInt / 100.0f;

  bool newHasSound = (type > 0);

  // 检测"长时间静默后突然出现"
  if (!hasSound && newHasSound) {
    // 之前无声, 现在有声
    if (now - silenceStart >= SILENCE_THRESHOLD) {
      // 触发突发提醒
      flashState = FLASHING;
      flashCount = 0;
      flashStartTime = now;
    }
  }

  hasSound = newHasSound;
  soundType = type;
  soundAngle = angle;
  soundDistance = distance;
  soundEnergy = energyInt;

  if (hasSound) {
    lastSoundTime = now;
    silenceStart = 0;  // 重置静默计时
  } else {
    if (silenceStart == 0) {
      silenceStart = now;
    }
  }

  // 非闪屏状态下正常绘制
  if (flashState != FLASHING) {
    drawCompassBackground(sprite);
    if (hasSound) {
      uint16_t iconColor;
      if (soundType == TYPE_FOOTSTEP) {
        iconColor = COLOR_BLUE;
      } else if (soundType == TYPE_GUNSHOT) {
        iconColor = COLOR_RED;
      } else {
        iconColor = COLOR_WHITE;
      }
      drawSoundIcon(sprite, soundAngle, soundDistance, soundType, iconColor);
    }
    sprite.pushSprite(0, 0);
  }
}

// ========== 校验 ==========
bool validateChecksum(uint8_t *buf) {
  uint8_t checksum = 0;
  for (int i = 0; i < 7; i++) {
    checksum ^= buf[i];
  }
  return checksum == buf[7];
}
