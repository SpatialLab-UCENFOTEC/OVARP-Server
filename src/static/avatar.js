/**
 * Open Virtual Agent Research Platform (OVARP) - Avatar Rendering Engine
 *
 * Renders an interactive 3D embodied agent using Three.js and @pixiv/three-vrm.
 * Supports runtime model swapping between VRM models and FBX/GLTF static/rigged models.
 *
 * @author Alexander Barquero Elizondo, Ph.D. - UCR, ECCI/CITIC
 * @license MIT
 */
import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { VRMLoaderPlugin, VRMUtils, VRMExpressionPresetName } from '@pixiv/three-vrm';

export default class AvatarController {
    constructor() {
        // Core 3D engine state
        this._scene = null;
        this._camera = null;
        this._renderer = null;
        this._container = null;
        this._clock = new THREE.Clock();
        this._animationId = null;

        // Model state management
        this._currentModel = null;
        this._currentModelType = null; // 'vrm' | 'fbx' | 'gltf'
        this._mixer = null; // Three.js AnimationMixer for skeletal clips
        this._loadGeneration = 0;

        // Lip sync
        this._audioContext = null;
        this._analyser = null;
        this._dataArray = null;
        this._isLipSyncing = false;
        this._audioElement = null;
        this._currentMouthOpen = 0;

        // Emotion state
        this._currentEmotion = 'neutral';
        this._targetEmotion = 'neutral';
        this._emotionBlend = 0;

        // Blink state
        this._nextBlinkTime = 0;
        this._isBlinking = false;
        this._blinkProgress = 0;
    }

    /**
     * Initialize the 3D scene on a canvas/container element.
     */
    init(targetElement) {
        if (!targetElement) return;

        this._container = targetElement.tagName === 'CANVAS' ? targetElement.parentElement : targetElement;
        
        while (this._container.firstChild) {
            this._container.removeChild(this._container.firstChild);
        }

        const width = this._container.clientWidth || 400;
        const height = this._container.clientHeight || 400;

        this._scene = new THREE.Scene();
        this._scene.background = new THREE.Color(0x1a1a2e);

        this._camera = new THREE.PerspectiveCamera(45, width / height, 0.1, 1000);
        this._camera.position.set(0, 1.2, 2.5);

        this._renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false });
        this._renderer.setSize(width, height);
        this._renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));

        const dom = this._renderer.domElement;
        dom.style.width = '100%';
        dom.style.height = '100%';
        dom.style.display = 'block';

        this._container.appendChild(dom);

        // Lights
        const ambientLight = new THREE.AmbientLight(0xffffff, 2.0);
        this._scene.add(ambientLight);

        const dirLight = new THREE.DirectionalLight(0xffffff, 2.5);
        dirLight.position.set(2, 4, 3);
        this._scene.add(dirLight);

        const dirLight2 = new THREE.DirectionalLight(0x7b68ee, 1.5);
        dirLight2.position.set(-2, 2, -3);
        this._scene.add(dirLight2);

        this._resizeObserver = new ResizeObserver(() => this._onResize());
        this._resizeObserver.observe(this._container);

        this._nextBlinkTime = 2 + Math.random() * 4;
        this._animate();
        console.log('[Avatar] Container-mounted WebGLRenderer initialized');
    }

    /**
     * Authoritative model disposal.
     */
    disposeCurrentModel() {
        if (!this._currentModel) return;

        const root = (this._currentModelType === 'vrm' && this._currentModel.scene) ? this._currentModel.scene : this._currentModel;

        if (root && this._scene) {
            this._scene.remove(root);
        }

        if (this._currentModelType === 'vrm' && this._currentModel.scene) {
            try {
                VRMUtils.deepDispose(this._currentModel.scene);
            } catch(e) {
                console.warn('[Avatar] VRM deepDispose warning:', e);
            }
        } else if (root && root.traverse) {
            root.traverse((child) => {
                if (child.isMesh) {
                    if (child.geometry) child.geometry.dispose();
                    if (child.material) {
                        const mats = Array.isArray(child.material) ? child.material : [child.material];
                        mats.forEach(m => {
                            if (m.map) m.map.dispose();
                            m.dispose();
                        });
                    }
                }
            });
        }

        if (this._mixer) {
            try { this._mixer.stopAllAction(); } catch(e) {}
            this._mixer = null;
        }

        this._currentModel = null;
        this._currentModelType = null;
    }

    /**
     * Load a VRM or FBX model from a URL.
     */
    async loadModel(url) {
        const generation = ++this._loadGeneration;
        console.log(`[Avatar] Loading model [gen ${generation}]: ${url}`);
        if (window.avatarLog) window.avatarLog(`Loading model [gen ${generation}]: ${url}`);

        const cleanUrl = url.split('?')[0].toLowerCase();
        const isFbx = cleanUrl.endsWith('.fbx');

        if (isFbx) {
            try {
                try { await import('fflate'); } catch(e) { console.warn('[Avatar] fflate import note:', e); }
                
                let FBXLoaderModule;
                try {
                    FBXLoaderModule = await import('three/addons/loaders/FBXLoader.js');
                } catch(e) {
                    console.error('[Avatar] FBXLoader import FAILED:', e);
                    if (window.avatarLog) window.avatarLog(`FBXLoader import FAILED: ${e.message}`, 'error');
                    throw new Error(`Failed to import FBXLoader: ${e.message || e}`);
                }

                const FBXLoader = FBXLoaderModule.FBXLoader;
                const loader = new FBXLoader();

                const textureLoader = new THREE.TextureLoader();
                const texture = textureLoader.load('/models/friet256/FRIET256/model/tex.png', () => {
                    texture.colorSpace = THREE.SRGBColorSpace;
                    texture.flipY = true;
                    if (window.avatarLog) window.avatarLog('Loaded tex.png for FBX', 'success');
                });

                return new Promise((resolve, reject) => {
                    loader.load(
                        url,
                        (fbx) => {
                            if (generation !== this._loadGeneration) {
                                console.log(`[Avatar] Stale FBX load [gen ${generation}] discarded`);
                                return;
                            }

                            this.disposeCurrentModel();

                            let meshCount = 0;
                            fbx.traverse((child) => {
                                if (child.isMesh) {
                                    meshCount++;
                                    if (child.material) {
                                        const mats = Array.isArray(child.material) ? child.material : [child.material];
                                        mats.forEach(m => {
                                            m.map = texture;
                                            m.side = THREE.DoubleSide;
                                            m.needsUpdate = true;
                                        });
                                    }
                                }
                            });

                            fbx.updateMatrixWorld(true);
                            const box = new THREE.Box3().setFromObject(fbx);
                            const size = box.getSize(new THREE.Vector3());

                            const maxDim = Math.max(size.x, size.y, size.z);
                            if (maxDim > 0) {
                                const scale = 1.8 / maxDim;
                                fbx.scale.setScalar(scale);
                            }

                            fbx.updateMatrixWorld(true);
                            const box2 = new THREE.Box3().setFromObject(fbx);
                            const center2 = box2.getCenter(new THREE.Vector3());

                            fbx.position.set(-center2.x, -box2.min.y, -center2.z);
                            
                            // Check for embedded skeletal animation clips
                            if (fbx.animations && fbx.animations.length > 0) {
                                this._mixer = new THREE.AnimationMixer(fbx);
                                const action = this._mixer.clipAction(fbx.animations[0]);
                                action.play();
                                if (window.avatarLog) window.avatarLog(`Playing embedded FBX clip: ${fbx.animations[0].name || 'Idle'}`, 'info');
                            }

                            this._currentModel = fbx;
                            this._currentModelType = 'fbx';
                            this._scene.add(fbx);

                            this._camera.position.set(0, 1.2, 2.5);
                            this._camera.lookAt(0, 0.9, 0);
                            this._camera.updateProjectionMatrix();

                            if (window.avatarLog) window.avatarLog('FBX Friet 256 Mounted & Framed cleanly!', 'success');
                            console.log('[Avatar] FBX Model loaded successfully');
                            resolve(fbx);
                        },
                        (progress) => {
                            const pct = progress.total > 0 ? Math.round((progress.loaded / progress.total) * 100) : '?';
                            if (window.avatarLog) window.avatarLog(`FBX Download: ${pct}%`, 'info');
                        },
                        (error) => {
                            console.error('[Avatar] FBX load error:', error);
                            if (window.avatarLog) window.avatarLog(`FBX load error: ${error.message || error}`, 'error');
                            reject(error);
                        }
                    );
                });
            } catch(e) {
                console.error('[Avatar] FBX initialization error:', e);
                throw e;
            }
        }

        // --- VRM / GLTF Path ---
        const loader = new GLTFLoader();
        try {
            const { DRACOLoader } = await import('three/addons/loaders/DRACOLoader.js');
            const dracoLoader = new DRACOLoader();
            dracoLoader.setDecoderPath('https://www.gstatic.com/draco/versioned/decoders/1.5.7/');
            loader.setDRACOLoader(dracoLoader);
        } catch(e) {
            console.warn('[Avatar] DRACOLoader setup note:', e);
        }
        loader.register((parser) => new VRMLoaderPlugin(parser));

        return new Promise((resolve, reject) => {
            loader.load(
                url,
                (gltf) => {
                    if (generation !== this._loadGeneration) {
                        console.log(`[Avatar] Stale VRM/GLTF load [gen ${generation}] discarded`);
                        return;
                    }

                    this.disposeCurrentModel();

                    const vrm = gltf.userData.vrm;
                    if (vrm) {
                        VRMUtils.removeUnnecessaryJoints(gltf.scene);
                        this._currentModel = vrm;
                        this._currentModelType = 'vrm';
                        this._scene.add(vrm.scene);

                        this._setRestPose();
                        vrm.scene.rotation.y = 0.25;
                        this._frameModel();

                        if (window.avatarLog) window.avatarLog('VRM Model loaded successfully!', 'success');
                        console.log('[Avatar] VRM Model loaded successfully');
                        resolve(vrm);
                    } else {
                        const scene = gltf.scene;
                        this._currentModel = scene;
                        this._currentModelType = 'gltf';
                        this._scene.add(scene);
                        this._frameFBXModel(scene);

                        if (window.avatarLog) window.avatarLog('GLB/GLTF model mounted & framed', 'success');
                        resolve(scene);
                    }
                },
                (progress) => {
                    const pct = progress.total > 0 ? Math.round((progress.loaded / progress.total) * 100) : '?';
                    if (window.avatarLog) window.avatarLog(`Download: ${pct}%`, 'info');
                },
                (error) => {
                    console.error('[Avatar] Model load failed:', error);
                    if (window.avatarLog) window.avatarLog(`Model load failed: ${error.message || error}`, 'error');
                    reject(error);
                }
            );
        });
    }

    _frameFBXModel(fbx) {
        fbx.updateMatrixWorld(true);
        const box = new THREE.Box3().setFromObject(fbx);
        const size = box.getSize(new THREE.Vector3());
        const center = box.getCenter(new THREE.Vector3());

        const maxDim = Math.max(size.x, size.y, size.z);
        if (maxDim > 0 && isFinite(maxDim)) {
            const scale = 1.6 / maxDim;
            fbx.scale.setScalar(scale);
            fbx.updateMatrixWorld(true);
        }

        fbx.position.set(-center.x, -box.min.y, -center.z);
        fbx.updateMatrixWorld(true);

        const height = (size.y && isFinite(size.y) && size.y > 0) ? size.y : 1.6;
        this._camera.position.set(0, height * 0.65, height * 1.5);
        this._camera.lookAt(0, height * 0.5, 0);
        this._camera.updateProjectionMatrix();
    }

    _setRestPose() {
        const humanoid = (this._currentModelType === 'vrm' && this._currentModel) ? this._currentModel.humanoid : null;
        if (!humanoid) return;

        const rotateBone = (boneName, x, y, z) => {
            const bone = humanoid.getNormalizedBoneNode(boneName);
            if (bone) {
                bone.rotation.set(x, y, z);
            }
        };

        rotateBone('rightUpperArm', 0.1, 0, 1.2);
        rotateBone('leftUpperArm', 0.1, 0, -1.2);
        rotateBone('rightLowerArm', 0, 0, -0.2);
        rotateBone('leftLowerArm', 0, 0, 0.2);
        rotateBone('rightHand', 0.1, 0, -0.05);
        rotateBone('leftHand', 0.1, 0, 0.05);
        rotateBone('neck', 0, -0.15, 0);
        rotateBone('head', 0, -0.1, 0);
    }

    _frameModel() {
        if (this._currentModelType !== 'vrm' || !this._currentModel) return;
        const humanoid = this._currentModel.humanoid;
        if (humanoid) {
            const head = humanoid.getNormalizedBoneNode('head');
            if (head) {
                const headPos = new THREE.Vector3();
                head.getWorldPosition(headPos);
                this._camera.position.set(0.15, headPos.y + 0.02, 1.8);
                this._camera.lookAt(0.05, headPos.y - 0.03, 0);
            }
        }
    }

    connectAudio(audioElement) {
        try {
            this._audioElement = audioElement;
            if (!this._audioContext) {
                this._audioContext = new (window.AudioContext || window.webkitAudioContext)();
            }
            if (this._audioContext.state === 'suspended') {
                this._audioContext.resume();
            }
            this._analyser = this._audioContext.createAnalyser();
            this._analyser.fftSize = 256;
            this._analyser.smoothingTimeConstant = 0.6;
            this._dataArray = new Uint8Array(this._analyser.frequencyBinCount);

            if (!audioElement._oafSourceNode) {
                audioElement._oafSourceNode = this._audioContext.createMediaElementSource(audioElement);
            }
            audioElement._oafSourceNode.disconnect();
            audioElement._oafSourceNode.connect(this._analyser);
            this._analyser.connect(this._audioContext.destination);

            this._isLipSyncing = true;
        } catch (e) {
            console.warn('[Avatar] Lip sync setup failed:', e.message);
        }
    }

    setEmotion(emotionName) {
        const normalized = (emotionName || 'neutral').toLowerCase();
        this._targetEmotion = normalized;
    }

    _animate() {
        this._animationId = requestAnimationFrame(() => this._animate());

        const delta = this._clock.getDelta();
        const elapsed = this._clock.getElapsedTime();

        // 1. Advance skeletal AnimationMixer if clips exist (FBX / GLTF)
        if (this._mixer) {
            this._mixer.update(delta);
        }

        // 2. Universal procedural idle animation (breathing, float, micro-sway for ALL models)
        this._updateUniversalIdle(elapsed);

        // 3. Blink update for all model types (VRM expressionManager OR Mesh morphTargets)
        this._updateBlink(delta, elapsed);

        // 4. VRM-specific updates (spring bones, blend shapes, bone sway)
        if (this._currentModelType === 'vrm' && this._currentModel) {
            if (this._currentModel.humanoid) {
                this._updateBreathing(elapsed);
                this._updateHeadSway(elapsed);
            }

            if (this._currentModel.expressionManager) {
                this._updateLipSync(delta);
                this._updateEmotion(delta);
            }

            if (typeof this._currentModel.update === 'function') {
                this._currentModel.update(delta);
            }
        }

        if (this._renderer && this._scene && this._camera) {
            this._renderer.render(this._scene, this._camera);
        }
    }

    /**
     * Universal procedural idle animation.
     * Gives an organic breathing, floating, and sway motion to ANY 3D model (FBX, GLTF, VRM).
     */
    _updateUniversalIdle(elapsed) {
        if (!this._currentModel) return;
        const root = (this._currentModelType === 'vrm' && this._currentModel.scene) ? this._currentModel.scene : this._currentModel;
        if (!root) return;

        if (root._baseY === undefined) {
            root._baseY = root.position.y;
        }

        // Gentle breathing float (Y axis)
        const floatY = Math.sin(elapsed * 1.8) * 0.012;
        root.position.y = root._baseY + floatY;

        // Gentle subtle tilt (Z axis)
        root.rotation.z = Math.sin(elapsed * 0.9) * 0.008;

        // Subtle yaw sway for non-VRM models (Y axis)
        if (this._currentModelType !== 'vrm') {
            root.rotation.y = Math.sin(elapsed * 0.4) * 0.025;
        }
    }

    _updateBreathing(elapsed) {
        const humanoid = (this._currentModelType === 'vrm' && this._currentModel) ? this._currentModel.humanoid : null;
        if (!humanoid) return;

        const spine = humanoid.getNormalizedBoneNode('spine');
        if (spine) {
            const breathPhase = Math.sin(elapsed * 1.6);
            spine.rotation.x = breathPhase * 0.008;
        }
    }

    _updateBlink(delta, elapsed) {
        if (!this._isBlinking) {
            if (elapsed >= this._nextBlinkTime) {
                this._isBlinking = true;
                this._blinkProgress = 0;
            }
        }

        let blinkValue = 0;
        if (this._isBlinking) {
            this._blinkProgress += delta * 10;
            if (this._blinkProgress < 0.5) {
                blinkValue = this._blinkProgress * 2;
            } else if (this._blinkProgress < 1.0) {
                blinkValue = 1 - (this._blinkProgress - 0.5) * 2;
            } else {
                blinkValue = 0;
                this._isBlinking = false;
                this._nextBlinkTime = elapsed + 2 + Math.random() * 4;
            }
        }

        // VRM Expression Manager path
        const expr = (this._currentModelType === 'vrm' && this._currentModel) ? this._currentModel.expressionManager : null;
        if (expr) {
            expr.setValue(VRMExpressionPresetName.Blink, blinkValue);
            return;
        }

        // Non-VRM Mesh Morph Target path (e.g., friet256.glb with 'close', 'blink', or 'eye_close' targets)
        if (this._currentModel) {
            const root = this._currentModel.scene || this._currentModel;
            if (root && root.traverse) {
                root.traverse((child) => {
                    if (child.isMesh && child.morphTargetDictionary && child.morphTargetInfluences) {
                        const dict = child.morphTargetDictionary;
                        const blinkKey = dict['close'] !== undefined ? 'close' : dict['blink'] !== undefined ? 'blink' : dict['eye_close'] !== undefined ? 'eye_close' : null;
                        if (blinkKey !== null) {
                            child.morphTargetInfluences[dict[blinkKey]] = blinkValue;
                        }
                    }
                });
            }
        }
    }

    _updateLipSync(delta) {
        const expr = (this._currentModelType === 'vrm' && this._currentModel) ? this._currentModel.expressionManager : null;
        if (!expr) return;

        let targetMouth = 0;

        if (this._isLipSyncing && this._analyser && this._audioElement) {
            const isPlaying = !this._audioElement.paused && !this._audioElement.ended;
            if (isPlaying) {
                this._analyser.getByteFrequencyData(this._dataArray);
                let sum = 0;
                const speechBins = Math.min(16, this._dataArray.length);
                for (let i = 1; i < speechBins; i++) {
                    sum += this._dataArray[i];
                }
                const avg = sum / (speechBins - 1);
                targetMouth = Math.min(1, Math.max(0, (avg - 40) / 100));
            }
        }

        const openSpeed = 12;
        const closeSpeed = 6;
        if (targetMouth > this._currentMouthOpen) {
            this._currentMouthOpen += (targetMouth - this._currentMouthOpen) * Math.min(1, delta * openSpeed);
        } else {
            this._currentMouthOpen += (targetMouth - this._currentMouthOpen) * Math.min(1, delta * closeSpeed);
        }

        if (this._currentMouthOpen < 0.01) this._currentMouthOpen = 0;

        expr.setValue(VRMExpressionPresetName.Aa, this._currentMouthOpen * 0.7);
        expr.setValue(VRMExpressionPresetName.Oh, this._currentMouthOpen * 0.2);
    }

    _updateEmotion(delta) {
        const expr = (this._currentModelType === 'vrm' && this._currentModel) ? this._currentModel.expressionManager : null;
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

        if (this._currentEmotion !== 'neutral') {
            const preset = emotionMap[this._currentEmotion];
            if (preset) {
                expr.setValue(preset, this._emotionBlend * 0.7);
            }
        }
    }

    _updateHeadSway(elapsed) {
        const humanoid = (this._currentModelType === 'vrm' && this._currentModel) ? this._currentModel.humanoid : null;
        if (!humanoid) return;

        const head = humanoid.getNormalizedBoneNode('head');
        if (head) {
            head.rotation.y = -0.1 + Math.sin(elapsed * 0.3) * 0.015;
            head.rotation.x = Math.sin(elapsed * 0.5 + 1) * 0.008;
            head.rotation.z = Math.sin(elapsed * 0.4 + 2) * 0.004;
        }
    }

    _onResize() {
        if (!this._container || !this._camera || !this._renderer) return;

        const width = this._container.clientWidth;
        const height = this._container.clientHeight;
        if (width === 0 || height === 0) return;

        this._camera.aspect = width / height;
        this._camera.updateProjectionMatrix();
        this._renderer.setSize(width, height);
    }

    dispose() {
        this._loadGeneration++;
        if (this._animationId) cancelAnimationFrame(this._animationId);
        if (this._resizeObserver) this._resizeObserver.disconnect();
        this.disposeCurrentModel();
        if (this._renderer) {
            if (this._renderer.domElement && this._renderer.domElement.parentElement) {
                this._renderer.domElement.parentElement.removeChild(this._renderer.domElement);
            }
            this._renderer.dispose();
        }
        if (this._audioContext) this._audioContext.close();
    }
}
