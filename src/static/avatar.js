/**
 * Open Virtual Agent Research Platform (OVARP) — Avatar Rendering Engine
 *
 * Renders an interactive 3D embodied agent using Three.js and @pixiv/three-vrm.
 * Features include real-time lip sync driven by Web Audio API AnalyserNode,
 * emotion expressions mapped from LLM action calls, natural idle animations
 * (breathing, blinking, head sway), and runtime VRM model swapping.
 *
 * All dependencies are loaded via CDN import maps (see index.html).
 *
 * @author Alexander Barquero Elizondo, Ph.D. — UCR, ECCI/CITIC
 * @license MIT
 */
import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { VRMLoaderPlugin, VRMUtils, VRMExpressionPresetName } from '@pixiv/three-vrm';

export default class AvatarController {
    constructor() {
        // Internal state
        this._scene = null;
        this._camera = null;
        this._renderer = null;
        this._vrm = null;
        this._clock = new THREE.Clock();
        this._canvas = null;
        this._animationId = null;

        // Lip sync
        this._audioContext = null;
        this._analyser = null;
        this._dataArray = null;
        this._isLipSyncing = false;
        this._audioElement = null;
        this._currentMouthOpen = 0; // Smoothed mouth value

        // Emotion state
        this._currentEmotion = 'neutral';
        this._targetEmotion = 'neutral';
        this._emotionBlend = 0;

        // Blink
        this._nextBlinkTime = 0;
        this._isBlinking = false;
        this._blinkProgress = 0;
    }

    /**
     * Initialize the 3D scene on a canvas element.
     */
    init(canvasElement) {
        this._canvas = canvasElement;
        const width = canvasElement.clientWidth;
        const height = canvasElement.clientHeight;

        // Scene — dark gradient background
        this._scene = new THREE.Scene();
        this._scene.background = new THREE.Color(0x1a1a2e);

        // Camera — framed for upper body / head, offset slightly for 3/4 view
        this._camera = new THREE.PerspectiveCamera(22, width / height, 0.1, 20);
        this._camera.position.set(0.15, 1.35, 2.0);
        this._camera.lookAt(0, 1.3, 0);

        // Renderer
        this._renderer = new THREE.WebGLRenderer({
            canvas: canvasElement,
            antialias: true,
            alpha: false
        });
        this._renderer.setSize(width, height);
        this._renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
        this._renderer.toneMapping = THREE.ACESFilmicToneMapping;
        this._renderer.toneMappingExposure = 1.3;

        // Lighting — warm key light, cool fill, purple rim
        const ambientLight = new THREE.AmbientLight(0xffffff, 0.7);
        this._scene.add(ambientLight);

        const keyLight = new THREE.DirectionalLight(0xfff0dd, 1.8);
        keyLight.position.set(1.5, 2, 2.5);
        this._scene.add(keyLight);

        const fillLight = new THREE.DirectionalLight(0xb0c4de, 0.5);
        fillLight.position.set(-1.5, 1, 1);
        this._scene.add(fillLight);

        const rimLight = new THREE.DirectionalLight(0x7b68ee, 0.5);
        rimLight.position.set(0, 1.5, -2);
        this._scene.add(rimLight);

        // Handle resize
        this._resizeObserver = new ResizeObserver(() => this._onResize());
        this._resizeObserver.observe(canvasElement.parentElement);

        // Schedule first blink
        this._nextBlinkTime = 2 + Math.random() * 4;

        // Start render loop
        this._animate();
        console.log('[Avatar] Scene initialized');
    }

    /**
     * Load a VRM model from a URL.
     */
    async loadModel(url) {
        console.log(`[Avatar] Loading model from: ${url}`);
        const loader = new GLTFLoader();
        loader.register((parser) => new VRMLoaderPlugin(parser));

        return new Promise((resolve, reject) => {
            loader.load(
                url,
                (gltf) => {
                    const vrm = gltf.userData.vrm;
                    if (!vrm) {
                        reject(new Error('No VRM data found in model'));
                        return;
                    }

                    // Clean up previous model
                    if (this._vrm) {
                        this._scene.remove(this._vrm.scene);
                        VRMUtils.deepDispose(this._vrm.scene);
                    }

                    // Optimize and add to scene
                    VRMUtils.removeUnnecessaryJoints(gltf.scene);
                    this._vrm = vrm;
                    this._scene.add(vrm.scene);

                    // --- Pose the avatar naturally ---
                    this._setRestPose();

                    // --- 3/4 body rotation (body diagonal, face forward) ---
                    vrm.scene.rotation.y = 0.25; // ~15 degrees body rotation

                    // Auto-frame the camera to the head
                    this._frameModel();

                    console.log('[Avatar] Model loaded successfully');
                    console.log('[Avatar] Available expressions:',
                        vrm.expressionManager ?
                            Object.keys(vrm.expressionManager.expressionMap || {}) :
                            'none');

                    // Log available bones for debugging
                    if (vrm.humanoid) {
                        const boneNames = [];
                        for (const [name, bone] of Object.entries(vrm.humanoid.humanBones)) {
                            if (bone && bone.node) boneNames.push(name);
                        }
                        console.log('[Avatar] Available bones:', boneNames.join(', '));
                    }

                    resolve(vrm);
                },
                (progress) => {
                    const pct = progress.total > 0 ?
                        Math.round((progress.loaded / progress.total) * 100) : '?';
                    console.log(`[Avatar] Loading: ${pct}%`);
                },
                (error) => {
                    console.error('[Avatar] Failed to load model:', error);
                    reject(error);
                }
            );
        });
    }

    /**
     * Set the avatar to a natural rest pose (arms down, relaxed).
     * VRM models load in T-pose by default.
     */
    _setRestPose() {
        const humanoid = this._vrm.humanoid;
        if (!humanoid) return;

        // Helper to safely get and rotate a bone
        const rotateBone = (boneName, x, y, z) => {
            const bone = humanoid.getNormalizedBoneNode(boneName);
            if (bone) {
                bone.rotation.set(x, y, z);
            }
        };

        // Arms down from T-pose: rotate upper arms
        // VRM normalized bones: positive Z = arm goes DOWN for right, negative Z for left
        rotateBone('rightUpperArm', 0.1, 0, 1.2);    // Right arm down + slight forward
        rotateBone('leftUpperArm', 0.1, 0, -1.2);     // Left arm down + slight forward

        // Forearms: slight natural bend
        rotateBone('rightLowerArm', 0, 0, -0.2);       // Slight inward bend
        rotateBone('leftLowerArm', 0, 0, 0.2);

        // Hands relaxed
        rotateBone('rightHand', 0.1, 0, -0.05);
        rotateBone('leftHand', 0.1, 0, 0.05);

        // Head counter-rotation to face camera (compensate for body rotation)
        rotateBone('neck', 0, -0.15, 0);   // Neck turns back toward camera
        rotateBone('head', 0, -0.1, 0);    // Head faces forward

        console.log('[Avatar] Rest pose applied');
    }

    /**
     * Frame the camera to focus on the avatar's upper body.
     */
    _frameModel() {
        if (!this._vrm) return;

        const humanoid = this._vrm.humanoid;
        if (humanoid) {
            const head = humanoid.getNormalizedBoneNode('head');
            if (head) {
                const headPos = new THREE.Vector3();
                head.getWorldPosition(headPos);

                // Position camera to frame head and shoulders, slightly offset for 3/4
                this._camera.position.set(0.15, headPos.y + 0.02, 1.8);
                this._camera.lookAt(0.05, headPos.y - 0.03, 0);
            }
        }
    }

    /**
     * Connect an <audio> element for lip sync analysis.
     */
    connectAudio(audioElement) {
        try {
            this._audioElement = audioElement;

            // Create audio context if needed
            if (!this._audioContext) {
                this._audioContext = new (window.AudioContext || window.webkitAudioContext)();
            }

            // Resume context (autoplay policy)
            if (this._audioContext.state === 'suspended') {
                this._audioContext.resume();
            }

            // Create analyser
            this._analyser = this._audioContext.createAnalyser();
            this._analyser.fftSize = 256;
            this._analyser.smoothingTimeConstant = 0.6;
            this._dataArray = new Uint8Array(this._analyser.frequencyBinCount);

            // Connect audio element to analyser (only once per element)
            if (!audioElement._oafSourceNode) {
                audioElement._oafSourceNode = this._audioContext.createMediaElementSource(audioElement);
            }
            audioElement._oafSourceNode.disconnect();
            audioElement._oafSourceNode.connect(this._analyser);
            this._analyser.connect(this._audioContext.destination);

            this._isLipSyncing = true;
            console.log('[Avatar] Audio connected for lip sync');
        } catch (e) {
            console.warn('[Avatar] Lip sync setup failed:', e.message);
        }
    }

    /**
     * Set the avatar's emotion expression.
     */
    setEmotion(emotionName) {
        const normalized = (emotionName || 'neutral').toLowerCase();
        this._targetEmotion = normalized;
        console.log(`[Avatar] Emotion set: ${normalized}`);
    }

    /**
     * Main animation loop.
     */
    _animate() {
        this._animationId = requestAnimationFrame(() => this._animate());

        const delta = this._clock.getDelta();
        const elapsed = this._clock.getElapsedTime();

        if (this._vrm) {
            // 1. Breathing animation
            this._updateBreathing(elapsed);

            // 2. Blink animation
            this._updateBlink(delta, elapsed);

            // 3. Lip sync from audio
            this._updateLipSync(delta);

            // 4. Emotion expression
            this._updateEmotion(delta);

            // 5. Subtle head sway (gentler to not fight counter-rotation)
            this._updateHeadSway(elapsed);

            // Update VRM spring bones etc.
            this._vrm.update(delta);
        }

        this._renderer.render(this._scene, this._camera);
    }

    /**
     * Breathing: move spine slightly up/down for visible chest movement.
     */
    _updateBreathing(elapsed) {
        const humanoid = this._vrm.humanoid;
        if (!humanoid) return;

        // Spine forward lean on inhale (visible breathing)
        const spine = humanoid.getNormalizedBoneNode('spine');
        if (spine) {
            const breathPhase = Math.sin(elapsed * 1.6);
            spine.rotation.x = breathPhase * 0.008;
        }
    }

    /**
     * Natural blink: random intervals, quick close/open.
     */
    _updateBlink(delta, elapsed) {
        const expr = this._vrm.expressionManager;
        if (!expr) return;

        if (!this._isBlinking) {
            if (elapsed >= this._nextBlinkTime) {
                this._isBlinking = true;
                this._blinkProgress = 0;
            }
        }

        if (this._isBlinking) {
            this._blinkProgress += delta * 10; // Fast blink ~0.1s

            let blinkValue;
            if (this._blinkProgress < 0.5) {
                blinkValue = this._blinkProgress * 2;
            } else if (this._blinkProgress < 1.0) {
                blinkValue = 1 - (this._blinkProgress - 0.5) * 2;
            } else {
                blinkValue = 0;
                this._isBlinking = false;
                this._nextBlinkTime = elapsed + 2 + Math.random() * 4;
            }

            expr.setValue(VRMExpressionPresetName.Blink, blinkValue);
        }
    }

    /**
     * Lip sync: map audio frequency to mouth open blend shape.
     * Smoothly closes mouth when audio stops or is silent.
     */
    _updateLipSync(delta) {
        const expr = this._vrm.expressionManager;
        if (!expr) return;

        let targetMouth = 0;

        // Only analyze if we have an active audio stream
        if (this._isLipSyncing && this._analyser && this._audioElement) {
            // Check if audio is actually playing
            const isPlaying = !this._audioElement.paused && !this._audioElement.ended;

            if (isPlaying) {
                this._analyser.getByteFrequencyData(this._dataArray);

                // Focus on speech frequencies (300Hz - 3000Hz)
                let sum = 0;
                const speechBins = Math.min(16, this._dataArray.length);
                for (let i = 1; i < speechBins; i++) {
                    sum += this._dataArray[i];
                }
                const avg = sum / (speechBins - 1);

                // Map to 0-1 with threshold
                targetMouth = Math.min(1, Math.max(0, (avg - 40) / 100));
            }
        }

        // Smooth mouth movement (fast open, slower close)
        const openSpeed = 12;
        const closeSpeed = 6;
        if (targetMouth > this._currentMouthOpen) {
            this._currentMouthOpen += (targetMouth - this._currentMouthOpen) * Math.min(1, delta * openSpeed);
        } else {
            this._currentMouthOpen += (targetMouth - this._currentMouthOpen) * Math.min(1, delta * closeSpeed);
        }

        // Snap to zero when very close (prevent stuck micro-open mouth)
        if (this._currentMouthOpen < 0.01) this._currentMouthOpen = 0;

        // Apply to blend shapes
        expr.setValue(VRMExpressionPresetName.Aa, this._currentMouthOpen * 0.7);
        expr.setValue(VRMExpressionPresetName.Oh, this._currentMouthOpen * 0.2);
    }

    /**
     * Map emotion names to VRM expressions with smooth blending.
     */
    _updateEmotion(delta) {
        const expr = this._vrm.expressionManager;
        if (!expr) return;

        const blendSpeed = 3.0;

        const emotionMap = {
            'happy': VRMExpressionPresetName.Happy,
            'sad': VRMExpressionPresetName.Sad,
            'angry': VRMExpressionPresetName.Angry,
            'surprised': VRMExpressionPresetName.Surprised,
            'relaxed': VRMExpressionPresetName.Relaxed,
            'neutral': VRMExpressionPresetName.Neutral,
        };

        // Fade out current emotion
        if (this._currentEmotion !== this._targetEmotion) {
            this._emotionBlend -= delta * blendSpeed;
            if (this._emotionBlend <= 0) {
                const oldPreset = emotionMap[this._currentEmotion];
                if (oldPreset) expr.setValue(oldPreset, 0);
                this._currentEmotion = this._targetEmotion;
                this._emotionBlend = 0;
            }
        } else {
            this._emotionBlend = Math.min(1, this._emotionBlend + delta * blendSpeed);
        }

        // Apply current emotion
        if (this._currentEmotion !== 'neutral') {
            const preset = emotionMap[this._currentEmotion];
            if (preset) {
                expr.setValue(preset, this._emotionBlend * 0.7);
            }
        }
    }

    /**
     * Subtle head sway for more natural idle appearance.
     * Gentle so it doesn't fight the forward-facing counter-rotation.
     */
    _updateHeadSway(elapsed) {
        const humanoid = this._vrm.humanoid;
        if (!humanoid) return;

        const head = humanoid.getNormalizedBoneNode('head');
        if (head) {
            // Add sway ON TOP of the counter-rotation (-0.1 base)
            head.rotation.y = -0.1 + Math.sin(elapsed * 0.3) * 0.015;
            head.rotation.x = Math.sin(elapsed * 0.5 + 1) * 0.008;
            head.rotation.z = Math.sin(elapsed * 0.4 + 2) * 0.004;
        }
    }

    /**
     * Handle canvas resize.
     */
    _onResize() {
        if (!this._canvas || !this._camera || !this._renderer) return;

        const width = this._canvas.parentElement.clientWidth;
        const height = this._canvas.parentElement.clientHeight;

        this._camera.aspect = width / height;
        this._camera.updateProjectionMatrix();
        this._renderer.setSize(width, height);
    }

    /**
     * Clean up all resources.
     */
    dispose() {
        if (this._animationId) cancelAnimationFrame(this._animationId);
        if (this._resizeObserver) this._resizeObserver.disconnect();
        if (this._vrm) VRMUtils.deepDispose(this._vrm.scene);
        if (this._renderer) this._renderer.dispose();
        if (this._audioContext) this._audioContext.close();
        console.log('[Avatar] Disposed');
    }
}
