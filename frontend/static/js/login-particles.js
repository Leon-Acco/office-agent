/**
 * 粒子笑脸吉祥物(Three.js WebGL GPU 粒子系统,工厂模式)
 *
 * 设计说明:
 * - 粒子按 Fibonacci 球面均匀分布(小颗粒高密度),vertex shader 中做
 *   假方向光漫反射 + rim light 轮廓光 + 背面粒子缩小减淡(纵深景深),
 *   构成有明暗体积感的光球;球后 DOM 暗晕负责与暖米背景分离。
 * - 五官用结构化低差异采样:眼睛 Fibonacci 圆盘铺满椭圆、左右镜像对称;
 *   嘴巴沿弧长均匀取点叠 sine 波浪 + 法向窄幅抖动,高密度小粒子堆出平滑
 *   波形,且嘴部粒子在 shader 中随时间游走起伏(波浪是"活"的)。
 * - 所有粒子动画(入场汇聚/鼠标排斥/爆散/呼吸)都在 vertex shader 中完成,
 *   CPU 每帧只更新少量 uniform,不在帧循环内创建任何对象。
 * - 混合模式:浅色奶油背景上 AdditiveBlending 只能增亮,
 *   白粒子和近黑五官都会不可见,故用正常混合+软圆 alpha 贴图,
 *   光晕感由 DOM 层 radial-gradient 承担(视觉等效)。
 * - 画布边缘淡出:粒子飞出视野时在 NDC 边缘柔和消隐,不被 canvas
 *   方形边界硬裁剪(否则球外会看出一个方框)。
 *
 * 对外 API:
 *   window.createParticleFace(canvas, opts) —— 工厂:在任意 canvas 上创建一个粒子笑脸
 *     opts.particleCount 粒子数(缺省按设备自动降级)
 *     opts.interactive   是否响应鼠标对视/排斥与表单聚焦(仅登录页主实例开启)
 *     opts.config        覆盖任意 CONFIG 项
 *     返回 { explode, setFormFocus, replay };WebGL 不可用时返回 null
 *   window.ParticleFace —— 登录页主实例(#particle-face)的 API
 */
(function () {
  'use strict';

  // ============================================
  // 默认可调参数(集中配置,单位见注释;可用 opts.config 覆盖)
  // ============================================
  var CONFIG = {
    PARTICLE_COUNT_DESKTOP: 60000, // 桌面粒子总数(含五官加密粒子,小颗粒高密度)
    PARTICLE_COUNT_MOBILE: 12000,  // 移动端/低配降级上限
    FEATURE_RATIO: 0.16,           // 五官加密粒子占比(高密度小粒子构成平滑形状)
    SPHERE_RADIUS: 1.0,            // 光球半径(世界单位)
    RADIUS_JITTER: 0.015,          // 半径抖动,制造体积感
    COLOR_BODY: [0.984, 1.0, 0.996],      // 球体本体:冷白微青 #FBFFFE
    COLOR_BODY_TINT: [0.051, 0.580, 0.533],// 色相偏移目标:teal #0D9488
    BODY_TINT_AMOUNT: 0.18,        // 本体粒子向 teal 偏移的最大比例
    COLOR_FEATURE: [0.055, 0.165, 0.149],  // 五官:深青墨 #0E2A26(小颗粒高密度后不再用死黑)
    SIZE_BODY: 0.011,              // 本体粒子尺寸(世界单位,小颗粒高密堆叠出体积)
    SIZE_FEATURE: 0.013,           // 五官粒子尺寸(与本体接近,靠密度而非颗粒大小成形)
    EYE_CX: 0.38,                  // 眼睛中心 x(左右镜像)
    EYE_CY: 0.28,                  // 眼睛中心 y
    EYE_RX: 0.135,                 // 眼睛椭圆半宽
    EYE_RY: 0.19,                  // 眼睛椭圆半高
    MOUTH_HALF: 0.46,              // 笑弧半宽
    MOUTH_BASE: -0.28,             // 笑弧弧底 y
    MAX_ROTATION: 18 * Math.PI / 180, // 对视最大旋转角 ±18°
    FORM_FOCUS_ROT: 12 * Math.PI / 180, // 表单聚焦时额外右转 12°
    ROT_DAMPING: 0.055,            // 旋转缓动系数(越小越柔)
    REPEL_RADIUS: 0.5,             // 鼠标排斥影响半径(世界单位)
    REPEL_STRENGTH: 0.28,          // 排斥最大位移
    BREATH_PERIOD: 4.0,            // 呼吸周期(秒)
    BREATH_AMP: 0.02,              // 呼吸缩放幅度 2%
    FLOAT_AMP: 0.035,              // 上下漂浮幅度(世界单位)
    ENTRANCE_DURATION: 1.5,        // 入场汇聚耗时(秒),easeOutExpo
    EXPLODE_OUT: 0.14,             // 爆散推出耗时(秒)
    EXPLODE_BACK: 0.9,             // 重聚耗时(秒)
    CAMERA_Z: 3.0,                 // 相机距离
    FOV: 42,                       // 相机视场角
    MAX_DPR: 2,                    // 像素比上限(高分屏性能保护)
    LIGHT_DIR: [-0.45, 0.75, 0.65],// 假方向光(左上前方),在 shader 中归一化
    LIGHT_AMBIENT: 0.78,           // 环境光底(背光面最低亮度,避免背光面过暗显脏)
    LIGHT_DIFFUSE: 0.22,           // 漫反射强度
    RIM_STRENGTH: 0.30,            // rim light 轮廓光强度(球体与背景分离的关键)
    MOUTH_WAVE_AMP: 0.055,         // 波浪嘴静态振幅(世界单位)
    MOUTH_WAVE_FREQ: 6.8,          // 波浪空间频率(约 1 个完整波形横跨嘴宽)
    MOUTH_WAVE_ANIM: 0.028,        // 波浪游走动效振幅(shader 内随时间起伏)
    MOUTH_WAVE_SPEED: 2.4,         // 波浪游走角速度(rad/s)
  };

  var reducedMotionGlobal = window.matchMedia &&
    window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  /**
   * 工厂:在指定 canvas 上创建一个粒子笑脸实例
   * @param {HTMLCanvasElement} canvas 目标画布
   * @param {Object} [opts] { particleCount, interactive, config }
   * @returns {Object|null} { explode, setFormFocus, replay };WebGL 不可用返回 null
   */
  function createParticleFace(canvas, opts) {
    if (!canvas) return null;
    opts = opts || {};
    var cfg = {};
    var k;
    for (k in CONFIG) cfg[k] = CONFIG[k];
    if (opts.config) for (k in opts.config) cfg[k] = opts.config[k];
    var interactive = !!opts.interactive;
    var reducedMotion = reducedMotionGlobal;

    // 粒子数自动降级:窄屏 / 低核数 / 显式 save-data
    var isMobile = window.innerWidth < 768;
    var lowPower = (navigator.hardwareConcurrency || 8) <= 4 ||
      (navigator.connection && navigator.connection.saveData);
    var PARTICLE_COUNT = opts.particleCount ||
      ((isMobile || lowPower) ? cfg.PARTICLE_COUNT_MOBILE : cfg.PARTICLE_COUNT_DESKTOP);

    if (typeof THREE === 'undefined') {
      showFallback();
      return null;
    }

    // ============================================
    // 粒子几何生成(仅初始化一次)
    // ============================================

    // 五官参数(face-space:x 右、y 上,正面朝 +Z;可由 opts.config 覆盖做"可爱度"调形)
    // 眼睛:椭圆;嘴巴:sine 波浪(静态主波形 + shader 游走起伏)。左右眼共用同一套样本镜像生成,保证完全对称
    var EYE_CX = cfg.EYE_CX, EYE_CY = cfg.EYE_CY, EYE_RX = cfg.EYE_RX, EYE_RY = cfg.EYE_RY;
    var MOUTH_HALF = cfg.MOUTH_HALF; // 笑弧半宽
    var MOUTH_BASE = cfg.MOUTH_BASE; // 弧底 y
    var MOUTH_JITTER = 0.03;  // 沿弧法向抖动半幅(笔触厚度)

    var featureCount = Math.floor(PARTICLE_COUNT * cfg.FEATURE_RATIO);
    var bodyCount = PARTICLE_COUNT - featureCount;

    var positions = new Float32Array(PARTICLE_COUNT * 3);
    var scatters = new Float32Array(PARTICLE_COUNT * 3);
    var colors = new Float32Array(PARTICLE_COUNT * 3);
    var sizes = new Float32Array(PARTICLE_COUNT);
    var seeds = new Float32Array(PARTICLE_COUNT);
    var waves = new Float32Array(PARTICLE_COUNT); // 1=波浪嘴粒子(参与 shader 游走动效)

    var R = cfg.SPHERE_RADIUS;
    var goldenAngle = Math.PI * (3 - Math.sqrt(5));

    function writeParticle(i, x, y, z, col, size) {
      var i3 = i * 3;
      positions[i3] = x; positions[i3 + 1] = y; positions[i3 + 2] = z;
      // 入场散点:半径 2.5~4.5 的随机球壳
      var sr = 2.5 + Math.random() * 2.0;
      var st = Math.random() * Math.PI * 2;
      var sp = Math.acos(2 * Math.random() - 1);
      scatters[i3] = sr * Math.sin(sp) * Math.cos(st);
      scatters[i3 + 1] = sr * Math.sin(sp) * Math.sin(st);
      scatters[i3 + 2] = sr * Math.cos(sp);
      colors[i3] = col[0]; colors[i3 + 1] = col[1]; colors[i3 + 2] = col[2];
      sizes[i] = size;
      seeds[i] = Math.random();
    }

    // 本体粒子:Fibonacci 球面均匀分布
    var i, t, y, r, theta, x, z, jx, tint, col;
    for (i = 0; i < bodyCount; i++) {
      t = (i + 0.5) / bodyCount;
      y = 1 - 2 * t;
      r = Math.sqrt(Math.max(0, 1 - y * y));
      theta = goldenAngle * i;
      x = Math.cos(theta) * r;
      z = Math.sin(theta) * r;
      jx = R + (Math.random() - 0.5) * 2 * cfg.RADIUS_JITTER;
      // 暖白 → teal 的轻微随机色相偏移
      tint = Math.random() * cfg.BODY_TINT_AMOUNT;
      col = [
        cfg.COLOR_BODY[0] * (1 - tint) + cfg.COLOR_BODY_TINT[0] * tint,
        cfg.COLOR_BODY[1] * (1 - tint) + cfg.COLOR_BODY_TINT[1] * tint,
        cfg.COLOR_BODY[2] * (1 - tint) + cfg.COLOR_BODY_TINT[2] * tint,
      ];
      writeParticle(i, x * jx, y * jx, z * jx, col, cfg.SIZE_BODY * (0.8 + Math.random() * 0.4));
    }

    // 五官粒子:结构化低差异采样(非拒绝采样)——
    // 眼睛用 Fibonacci 圆盘铺满椭圆,一套样本左右镜像,天然对称;
    // 嘴巴沿弧长参数均匀取点叠在 sine 波浪上 + 法向窄幅抖动,
    // 得到平滑连续的波浪嘴;波浪粒子标记 aWave=1,shader 中再做游走起伏
    var featIdx = 0;
    var eyeEach = Math.floor(featureCount * 0.24); // 单眼粒子数(约占五官总量 1/4)
    var mouthCount = featureCount - eyeEach * 2;
    var side, ex, ey;
    for (i = 0; i < eyeEach; i++) {
      t = (i + 0.5) / eyeEach;
      r = Math.sqrt(t);                 // 等面积圆盘分布
      theta = goldenAngle * i;
      ex = r * Math.cos(theta) * EYE_RX;
      ey = r * Math.sin(theta) * EYE_RY;
      for (side = -1; side <= 1; side += 2) {
        x = side * EYE_CX + ex;
        y = EYE_CY + ey;
        z = Math.sqrt(Math.max(0, 1 - x * x - y * y));
        jx = R + (Math.random() - 0.5) * 2 * cfg.RADIUS_JITTER;
        writeParticle(bodyCount + featIdx, x * jx, y * jx, z * jx,
          cfg.COLOR_FEATURE, cfg.SIZE_FEATURE * (0.85 + Math.random() * 0.3));
        featIdx++;
      }
    }
    for (i = 0; i < mouthCount; i++) {
      t = (i + 0.5) / mouthCount;
      x = -MOUTH_HALF + 2 * MOUTH_HALF * t;
      // 波浪嘴:sine 主波形 + 法向窄幅抖动(笔触厚度)
      y = MOUTH_BASE + cfg.MOUTH_WAVE_AMP * Math.sin(x * cfg.MOUTH_WAVE_FREQ) +
        (Math.random() * 2 - 1) * MOUTH_JITTER;
      z = Math.sqrt(Math.max(0, 1 - x * x - y * y));
      jx = R + (Math.random() - 0.5) * 2 * cfg.RADIUS_JITTER;
      writeParticle(bodyCount + featIdx, x * jx, y * jx, z * jx,
        cfg.COLOR_FEATURE, cfg.SIZE_FEATURE * (0.85 + Math.random() * 0.3));
      waves[bodyCount + featIdx] = 1;
      featIdx++;
    }

    // ============================================
    // 渲染器 / 场景 / 材质
    // ============================================
    var renderer;
    try {
      renderer = new THREE.WebGLRenderer({
        canvas: canvas, alpha: true, antialias: false, powerPreference: 'high-performance',
      });
    } catch (e) {
      showFallback();
      return null;
    }
    renderer.setClearColor(0x000000, 0);

    var scene = new THREE.Scene();
    var camera = new THREE.PerspectiveCamera(cfg.FOV, 1, 0.1, 100);
    camera.position.z = cfg.CAMERA_Z;

    var geometry = new THREE.BufferGeometry();
    geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));
    geometry.setAttribute('aScatter', new THREE.BufferAttribute(scatters, 3));
    geometry.setAttribute('aSize', new THREE.BufferAttribute(sizes, 1));
    geometry.setAttribute('aSeed', new THREE.BufferAttribute(seeds, 1));
    geometry.setAttribute('aWave', new THREE.BufferAttribute(waves, 1));
    geometry.setAttribute('color', new THREE.BufferAttribute(colors, 3));

    var uniforms = {
      uTime: { value: 0 },
      uProgress: { value: reducedMotion ? 1 : 0 }, // 降级模式直接呈现最终形态
      uExplode: { value: 0 },
      uMouse: { value: new THREE.Vector3(999, 999, 0) }, // 局部坐标系下的鼠标点
      uRepelRadius: { value: cfg.REPEL_RADIUS },
      uRepelStrength: { value: cfg.REPEL_STRENGTH },
      uBreathAmp: { value: reducedMotion ? 0 : cfg.BREATH_AMP },
      uBreathFreq: { value: (Math.PI * 2) / cfg.BREATH_PERIOD },
      uPixelScale: { value: 1 },
    };

    // 光照常量以字面量注入 shader(初始化后不再变化,省 uniform 开销)
    var lightLen = Math.sqrt(
      cfg.LIGHT_DIR[0] * cfg.LIGHT_DIR[0] +
      cfg.LIGHT_DIR[1] * cfg.LIGHT_DIR[1] +
      cfg.LIGHT_DIR[2] * cfg.LIGHT_DIR[2]);
    var LDIR = 'vec3(' +
      (cfg.LIGHT_DIR[0] / lightLen).toFixed(4) + ',' +
      (cfg.LIGHT_DIR[1] / lightLen).toFixed(4) + ',' +
      (cfg.LIGHT_DIR[2] / lightLen).toFixed(4) + ')';

    var material = new THREE.ShaderMaterial({
      uniforms: uniforms,
      vertexColors: true,
      transparent: true,
      depthWrite: false,
      depthTest: false,
      blending: THREE.NormalBlending, // 浅背景上加法混合不可见,见文件头说明
      vertexShader: [
        'uniform float uTime;',
        'uniform float uProgress;',
        'uniform float uExplode;',
        'uniform vec3 uMouse;',
        'uniform float uRepelRadius;',
        'uniform float uRepelStrength;',
        'uniform float uBreathAmp;',
        'uniform float uBreathFreq;',
        'uniform float uPixelScale;',
        'attribute vec3 aScatter;',
        'attribute float aSize;',
        'attribute float aSeed;',
        'attribute float aWave;',
        'varying vec3 vColor;',
        'varying float vAlpha;',
        'void main() {',
        '  vec3 n = normalize(position);',
        '  // 假光照:方向光漫反射 + rim light 轮廓光,球体才有明暗体积感',
        '  float ndl = max(dot(n, ' + LDIR + '), 0.0);',
        '  float shade = ' + cfg.LIGHT_AMBIENT.toFixed(3) + ' + ' +
          cfg.LIGHT_DIFFUSE.toFixed(3) + ' * ndl;',
        '  shade += pow(1.0 - abs(n.z), 2.5) * ' + cfg.RIM_STRENGTH.toFixed(3) + ';',
        '  // 纵深景深:背面粒子更小更淡,正面实——打破"均匀铺满的平面感"',
        '  float depthCue = n.z * 0.5 + 0.5;',
        '  vColor = color * shade;',
        '  vAlpha = 0.30 + 0.70 * depthCue;',
        '  // 入场:散乱点 → 球面(uProgress 已在 CPU 做 easeOutExpo)',
        '  vec3 pos = mix(aScatter, position, uProgress);',
        '  // 波浪嘴:嘴部粒子沿 y 随时间游走起伏,波浪"活"起来',
        '  pos.y += aWave * ' + cfg.MOUTH_WAVE_ANIM.toFixed(3) +
          ' * sin(position.x * ' + cfg.MOUTH_WAVE_FREQ.toFixed(2) +
          ' + uTime * ' + cfg.MOUTH_WAVE_SPEED.toFixed(2) + ');',
        '  // 爆散:沿法线推出,各粒子带随机系数',
        '  pos += n * uExplode * (0.5 + 0.9 * aSeed);',
        '  // 鼠标排斥:与射线-球面求交得到的表面点做 3D 距离,鼠标移走自动回位',
        '  // 注意:不能用 z=0 平面投影(球心处纵深 0.84 会吞掉 REPEL_RADIUS),',
        '  // 也不能对平面点取方向做角距离(锥心会偏到轮廓边缘)',
        '  float d = distance(position, uMouse);',
        '  float f = 1.0 - smoothstep(0.0, uRepelRadius, d);',
        '  pos += n * f * uRepelStrength * (0.6 + 0.4 * aSeed);',
        '  // 呼吸:低频整体缩放',
        '  pos *= 1.0 + uBreathAmp * sin(uTime * uBreathFreq);',
        '  vec4 mv = modelViewMatrix * vec4(pos, 1.0);',
        '  gl_PointSize = aSize * (0.72 + 0.45 * depthCue) * uPixelScale / max(0.1, -mv.z);',
        '  vec4 clip = projectionMatrix * mv;',
        '  gl_Position = clip;',
        '  // 画布边缘淡出:入场散点/爆散/排斥粒子飞出视野时在 NDC 边缘柔和消隐,',
        '  // 不再被 canvas 方形边界硬裁剪(否则球外会看出一个方框)',
        '  vec2 ndc = clip.xy / clip.w;',
        '  float edge = max(abs(ndc.x), abs(ndc.y));',
        '  vAlpha *= 1.0 - smoothstep(0.86, 1.0, edge);',
        '}',
      ].join('\n'),
      fragmentShader: [
        'varying vec3 vColor;',
        'varying float vAlpha;',
        'void main() {',
        '  // 程序化软圆贴图:中心实、边缘柔(edge0 < edge1,规范写法)',
        '  float d = length(gl_PointCoord - 0.5);',
        '  float alpha = (1.0 - smoothstep(0.08, 0.5, d)) * vAlpha;',
        '  if (alpha < 0.01) discard;',
        '  gl_FragColor = vec4(vColor, alpha);',
        '}',
      ].join('\n'),
    });

    var points = new THREE.Points(geometry, material);
    scene.add(points);

    // ============================================
    // 交互状态(帧循环复用,禁止每帧新建对象)
    // ============================================
    var targetRotX = 0, targetRotY = 0;   // 对视目标角
    var curRotX = 0, curRotY = 0;         // 缓动后的当前角
    var formFocusExtra = 0;               // 表单聚焦附加转角(缓动目标)
    var formFocusCur = 0;
    var mouseNdcX = 0, mouseNdcY = 0;     // 鼠标 NDC
    var mouseActive = false;
    var startTime = performance.now();
    var explodeT = -1;                     // 爆散进度时钟(-1 表示未触发)
    var running = false;
    var rafId = 0;

    // 帧循环复用的临时对象
    var tmpVec = new THREE.Vector3();
    var tmpCenter = new THREE.Vector3();
    var tmpRay = new THREE.Raycaster();

    // ============================================
    // 尺寸自适应
    // ============================================
    function resize() {
      var w = canvas.clientWidth || 1;
      var h = canvas.clientHeight || 1;
      var dpr = Math.min(window.devicePixelRatio || 1, cfg.MAX_DPR);
      renderer.setPixelRatio(dpr);
      renderer.setSize(w, h, false);
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
      // 世界单位 → 像素的换算因子(近大远小的透视点尺寸)
      uniforms.uPixelScale.value =
        (h * dpr) / (2 * Math.tan((cfg.FOV * Math.PI / 180) / 2));
      // 降级模式下尺寸变化后补一帧静态渲染(否则隐藏→显示的画布会空白)
      if (reducedMotion) renderer.render(scene, camera);
    }

    // ============================================
    // 鼠标交互(仅 interactive 实例注册)
    // ============================================
    var loginPage = document.getElementById('page-login');

    function onMouseMove(e) {
      var rect = canvas.getBoundingClientRect();
      if (rect.width === 0) return;
      var cx = rect.left + rect.width / 2;
      var cy = rect.top + rect.height / 2;
      // 以画布中心为原点的归一化偏移(半屏为 1)
      var nx = (e.clientX - cx) / (window.innerWidth / 2);
      var ny = (e.clientY - cy) / (window.innerHeight / 2);
      nx = Math.max(-1, Math.min(1, nx));
      ny = Math.max(-1, Math.min(1, ny));
      targetRotY = nx * cfg.MAX_ROTATION;
      targetRotX = ny * cfg.MAX_ROTATION;
      mouseNdcX = ((e.clientX - rect.left) / rect.width) * 2 - 1;
      mouseNdcY = -(((e.clientY - rect.top) / rect.height) * 2 - 1);
      mouseActive = true;
    }
    function onMouseLeave() {
      targetRotX = 0;
      targetRotY = 0;
      mouseActive = false;
    }

    // 表单聚焦:笑脸微微注视右侧表单
    function setFormFocus(focused) {
      formFocusExtra = focused ? cfg.FORM_FOCUS_ROT : 0;
    }

    // 爆散:推出后弹性重聚
    function explode() {
      if (reducedMotion) return;
      explodeT = 0;
    }

    // 重播入场汇聚(实例创建时画布不可见会跳过入场,显示前调用可补播)
    function replay() {
      if (reducedMotion) return;
      startTime = performance.now();
      resize();
      start();
    }

    // ============================================
    // 主循环
    // ============================================
    function easeOutExpo(t) {
      return t >= 1 ? 1 : 1 - Math.pow(2, -10 * t);
    }

    function frame(now) {
      if (!running) return;
      var elapsed = (now - startTime) / 1000;
      uniforms.uTime.value = elapsed;

      // 入场进度(easeOutExpo,CPU 每帧只算一次标量)
      var p = Math.min(1, elapsed / cfg.ENTRANCE_DURATION);
      uniforms.uProgress.value = easeOutExpo(p);

      // 爆散时钟
      if (explodeT >= 0) {
        explodeT += 1 / 60;
        if (explodeT < cfg.EXPLODE_OUT) {
          uniforms.uExplode.value = explodeT / cfg.EXPLODE_OUT;
        } else {
          var back = (explodeT - cfg.EXPLODE_OUT) / cfg.EXPLODE_BACK;
          uniforms.uExplode.value = Math.max(0, 1 - back);
          if (back >= 1) explodeT = -1;
        }
      }

      // 旋转缓动(对视 + 表单聚焦叠加)
      formFocusCur += (formFocusExtra - formFocusCur) * cfg.ROT_DAMPING;
      curRotX += (targetRotX - curRotX) * cfg.ROT_DAMPING;
      curRotY += (targetRotY - curRotY) * cfg.ROT_DAMPING;
      points.rotation.x = curRotX;
      points.rotation.y = curRotY + formFocusCur;

      // 上下漂浮
      points.position.y = cfg.FLOAT_AMP *
        Math.sin(elapsed * (Math.PI * 2) / cfg.BREATH_PERIOD);

      // 鼠标射线与球面求交(世界空间),把表面点写入 uMouse 供 shader 排斥
      if (mouseActive) {
        tmpRay.setFromCamera({ x: mouseNdcX, y: mouseNdcY }, camera);
        tmpCenter.set(0, 0, 0);
        points.localToWorld(tmpCenter); // 球心世界坐标
        tmpVec.copy(tmpRay.ray.origin).sub(tmpCenter);
        var rb = tmpVec.dot(tmpRay.ray.direction);
        var rc = tmpVec.lengthSq() - cfg.SPHERE_RADIUS * cfg.SPHERE_RADIUS;
        var disc = rb * rb - rc;
        var hitT = disc > 0 ? -rb - Math.sqrt(disc) : -1;
        if (hitT > 0) {
          tmpVec.copy(tmpRay.ray.direction).multiplyScalar(hitT).add(tmpRay.ray.origin);
          points.worldToLocal(tmpVec);
          uniforms.uMouse.value.copy(tmpVec);
        } else {
          // 光标在球体轮廓外:不参与排斥
          uniforms.uMouse.value.set(999, 999, 0);
        }
      } else {
        uniforms.uMouse.value.set(999, 999, 0);
      }

      renderer.render(scene, camera);
      rafId = requestAnimationFrame(frame);
    }

    function start() {
      if (running || reducedMotion) return;
      running = true;
      rafId = requestAnimationFrame(frame);
    }
    function stop() {
      running = false;
      if (rafId) cancelAnimationFrame(rafId);
      rafId = 0;
    }

    // ============================================
    // 生命周期:页面隐藏 / 画布不可见时暂停渲染
    // ============================================
    document.addEventListener('visibilitychange', function () {
      if (document.hidden) stop();
      else start();
    });
    if ('IntersectionObserver' in window) {
      new IntersectionObserver(function (entries) {
        if (entries[0].isIntersecting) {
          // 隐藏时创建的画布 clientWidth=0 会被钳成 1×1(显示后整片单色方块),
          // 重新可见时必须重算尺寸再渲染;reducedMotion 下 resize 内部会补静态帧
          resize();
          if (!reducedMotion) start();
        } else {
          stop();
        }
      }, { threshold: 0.01 }).observe(canvas);
    }

    // WebGL 不可用时的静态兜底
    function showFallback() {
      canvas.style.display = 'none';
      var wrap = canvas.parentElement;
      if (wrap) {
        var div = document.createElement('div');
        div.style.cssText = 'width:100%;height:100%;display:flex;align-items:center;justify-content:center;font-size:96px;';
        div.innerHTML = '<span class="material-symbols-outlined" style="font-size:96px;">sentiment_satisfied</span>';
        wrap.appendChild(div);
      }
    }

    // ============================================
    // 启动
    // ============================================
    resize();
    window.addEventListener('resize', resize);
    if (interactive) {
      // 布局切换(分栏/沉浸/居中)会改变画布尺寸,需即时重算渲染尺寸与像素比
      window.addEventListener('lp-layout-change', function () {
        resize();
      });
      if (loginPage && !reducedMotion) {
        loginPage.addEventListener('mousemove', onMouseMove);
        loginPage.addEventListener('mouseleave', onMouseLeave);
      }
      ['login-email', 'login-password'].forEach(function (id) {
        var el = document.getElementById(id);
        if (!el) return;
        el.addEventListener('focus', function () { setFormFocus(true); });
        el.addEventListener('blur', function () { setFormFocus(false); });
      });
    }

    if (reducedMotion) {
      // 降级:仅渲染一帧静态笑脸
      renderer.render(scene, camera);
    } else {
      start();
    }

    return {
      explode: explode,
      setFormFocus: setFormFocus,
      replay: replay,
      // 调试钩子(排查交互用,无业务依赖)
      _debug: { uniforms: uniforms, points: points, camera: camera },
    };
  }

  // ============================================
  // 登录页主实例(保持原有 window.ParticleFace API 不变)
  // ============================================
  window.createParticleFace = createParticleFace;
  // 浅色背景场景的配色预设:本体加深为 teal 系,浅底上球体才显形(五官沿用深青墨);
  // 同时加大颗粒与五官(大眼宽笑弧),吉祥物更明显更可爱
  window.PF_LIGHT_BG_CONFIG = {
    COLOR_BODY: [0.275, 0.675, 0.600],      // 球体本体:中 teal #46AC99(浅底清晰显形)
    COLOR_BODY_TINT: [0.051, 0.580, 0.533], // 色相偏移目标仍 teal #0D9488
    BODY_TINT_AMOUNT: 0.35,                 // 更多粒子偏向深 teal,增强明暗层次
    SIZE_BODY: 0.014,                       // 颗粒加大,球体更实
    SIZE_FEATURE: 0.017,                    // 五官颗粒加大,表情更清晰
    EYE_RX: 0.15,                           // 眼睛更圆更大(可爱度)
    EYE_RY: 0.21,
    MOUTH_HALF: 0.5,                        // 笑弧更宽
  };
  var mainCanvas = document.getElementById('particle-face');
  if (mainCanvas) {
    var api = createParticleFace(mainCanvas, { interactive: true });
    window.ParticleFace = api || { explode: function () {}, setFormFocus: function () {} };
    if (api) window.__pfDebug = api._debug;
  }
})();
