import AvatarController from '../avatar.js';

/**
 * OVARPClient: The official Web SDK for the Open Virtual Agent Research Platform.
 * Encapsulates all WebSocket communication, audio playback, mic streaming,
 * and 3D Avatar synchronization into a clean, framework-agnostic class.
 */
export default class OVARPClient {
    /**
     * Initialize the Web SDK.
     * @param {Object} config Configuration dictionary
     * @param {string} config.serverUrl - (Optional) The server address and port, e.g. "192.168.1.100:8000". Defaults to current host.
     * @param {string} config.deviceId - (Optional) Unicast ID. Defaults to "web_client_01".
     * @param {string} config.agentId - (Optional) Target Agent ID. Defaults to "agent_alpha".
     * @param {HTMLElement} config.canvas - (Optional) An HTMLCanvasElement where the 3D VRM will be rendered.
     * @param {Object} config.callbacks - (Optional) Dictionary of lifecycle hooks (onConnect, onMessage, onAgentAction, etc.)
     */
    constructor(config = {}) {
        this.serverUrl = config.serverUrl || window.location.host;
        this.protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        this.deviceId = config.deviceId || 'web_client_01';
        this.agentId = config.agentId || 'agent_alpha';

        // Hooks
        this.callbacks = Object.assign({
            onConnect: () => { },
            onDisconnect: () => { },
            onMessage: (msgSubcommand) => { }, // When text response arrives
            onAgentAction: (actionSubcommand) => { }, // When emotion/anim triggers
            onLog: (msg, type) => { }, // General SDK logs
            onTTSReady: (blobUrl) => { }, // When TTS audio blob is ready for playback
            onMarkerLogged: (label, metadata) => { }, // When an event marker is confirmed by server
            onMicStart: () => { },
            onMicStop: () => { }
        }, config.callbacks);

        this.ws = null;
        this.avatar = null;

        // Audio and STT
        this._mediaRecorder = null;
        this._audioChunks = [];
        this.isRecording = false;

        // TTS buffer
        this._ttsAudioChunks = [];
        this._ttsAudioPlayer = document.createElement('audio');
        this._ttsAudioPlayer.id = 'OVARP-tts-audio-player';
        document.body.appendChild(this._ttsAudioPlayer);

        if (config.canvas) {
            this._initAvatar(config.canvas);
        }
    }

    /** Mounts the AvatarController */
    _initAvatar(canvasElement) {
        this.avatar = new AvatarController();
        this.avatar.init(canvasElement);
        this.callbacks.onLog('Avatar Canvas mounted. Awaiting loadModel() call.', 'info');
    }

    /** Load a .vrm file into the avatar scene */
    async loadAvatar(url) {
        if (!this.avatar) throw new Error("Canvas was not provided during OVARPClient init.");
        this.callbacks.onLog(`Loading Avatar: ${url}`, 'info');
        await this.avatar.loadModel(url);
        this.callbacks.onLog(`Avatar Loaded successfully`, 'success');
    }

    /**
     * Connect to the OVARP Server via WebSockets.
     */
    connect() {
        // Close any existing connection to prevent duplicate sockets on the server
        if (this.ws) {
            this.ws.onclose = null;  // Prevent onDisconnect callback (and re-triggering reconnect)
            this.ws.onerror = null;
            this.ws.onmessage = null;
            if (this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CONNECTING) {
                this.ws.close();
            }
        }

        const wsUri = `${this.protocol}//${this.serverUrl}/ws/client/${this.deviceId}`;
        this.ws = new WebSocket(wsUri);

        this.ws.onopen = () => {
            this.callbacks.onConnect();
            this.callbacks.onLog('Connected to OVARP Router via SDK', 'success');
        };

        this.ws.onclose = () => {
            this.callbacks.onDisconnect();
            this.callbacks.onLog('Disconnected from OVARP Router', 'error');
        };

        this.ws.onerror = (e) => {
            this.callbacks.onLog('WebSocket Error', 'error');
        };

        this.ws.onmessage = this._handleTransportMessage.bind(this);
    }

    /**
     * Cleanly close WebSocket and cleanup Media/DOM.
     */
    disconnect() {
        if (this.ws) {
            this.ws.close();
            this.ws = null;
        }
    }

    // --- Outbound Routing ---

    /**
     * Send a low-level standard payload to the framework.
     */
    sendCommand(type, command, subcommand = {}) {
        if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
            this.callbacks.onLog('Cannot send: WebSocket not connected', 'error');
            return;
        }
        const payload = {
            sender: this.deviceId,
            target_device: 'all',
            target_agent: this.agentId,
            command_type: type,
            command: command,
            subcommand: subcommand
        };
        const jsonStr = JSON.stringify(payload);
        this.ws.send(jsonStr);
        this.callbacks.onLog(`[Outbound] ${command}`, 'sent');
    }

    /**
     * Request an LLM response via a Text query.
     * @param {string} text 
     */
    sendText(text) {
        this.sendCommand('message', 'llm_request', { text });
    }

    /**
     * Fire an event marker programmatically.
     * The server will log it to the active session and broadcast a confirmation.
     * @param {string} label - Event label, e.g. 'task_started'
     * @param {Object} metadata - Optional extra data to attach to the marker
     */
    addMarker(label, metadata = {}) {
        this.sendCommand('system', 'log_marker', { label, metadata });
    }

    // --- STT (Mic Recording) ---

    /**
     * Request microphone permissions and start recording an STT audio clip.
     */
    async startMic() {
        if (this.isRecording) return;
        try {
            const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
            this._mediaRecorder = new MediaRecorder(stream);
            this._audioChunks = [];

            this._mediaRecorder.ondataavailable = e => {
                if (e.data.size > 0) this._audioChunks.push(e.data);
            };

            this._mediaRecorder.onstop = async () => {
                const audioBlob = new Blob(this._audioChunks, { type: 'audio/webm' });
                const base64Audio = await this._blobToBase64(audioBlob);

                // IMPORTANT: OVARP Server expects raw base64 data without data-uri prefix
                const b64Data = base64Audio.split(',')[1];

                this.sendCommand('audio', 'stt_request', { audio_base64: b64Data });
                this.callbacks.onLog(`[Mic STT] Sending ${this._audioChunks.length} chunks`, 'info');

                // Cleanup tracks
                stream.getTracks().forEach(track => track.stop());
                this._audioChunks = [];
            };

            this._mediaRecorder.start();
            this.isRecording = true;
            this.callbacks.onMicStart();
            this.callbacks.onLog('Mic recording started', 'info');

        } catch (err) {
            this.callbacks.onLog(`[Mic Error] ${err.message}`, 'error');
        }
    }

    /**
     * Stop the microphone and automatically send the recording to the Server for transcription.
     */
    stopMic() {
        if (!this.isRecording || !this._mediaRecorder) return;
        this._mediaRecorder.stop();
        this.isRecording = false;
        this.callbacks.onMicStop();
        this.callbacks.onLog('Mic recording stopped', 'info');
    }

    // --- Inbound Routing ---

    _handleTransportMessage(event) {
        try {
            const raw = JSON.parse(event.data);
            // WS transport wraps messages in {"topic": "...", "payload": {...}}
            const data = raw.payload || raw;

            if (data.command_type === "audio" && data.sender === "server_orchestrator") {
                this._handleAudioCommand(data);
                return; // Suppress massive audio logs
            }

            this.callbacks.onLog(`[Inbound] ${data.command}`, 'recv');

            if (data.command_type === "message" && data.command === "llm_reply") {
                this.callbacks.onMessage(data.subcommand);
            }
            else if (data.command_type === "action" && data.command === "execute_state") {
                // Pipe directly to Avatar if it exists
                if (this.avatar) {
                    if (data.subcommand.emotions) {
                        this.avatar.setEmotion(data.subcommand.emotions);
                    }
                    if (data.subcommand.actions) {
                        // Assuming actions might trigger animations later
                        this.callbacks.onLog(`[Avatar Action] triggering ${data.subcommand.actions}`, 'info');
                    }
                }
                this.callbacks.onAgentAction(data.subcommand);
            }
            else if (data.command_type === "system" && data.command === "marker_logged") {
                // Server confirmed an event marker was logged
                const sub = data.subcommand || {};
                this.callbacks.onMarkerLogged(sub.label, sub.metadata);
                this.callbacks.onLog(`[Marker] ${sub.label}`, 'info');
            }

        } catch (err) {
            this.callbacks.onLog(`Failed to parse WS message: ${err}`, 'error');
        }
    }

    _handleAudioCommand(data) {
        if (data.command === "tts_chunk" && data.subcommand && data.subcommand.audio_base64) {
            const binaryStr = atob(data.subcommand.audio_base64);
            const bytes = new Uint8Array(binaryStr.length);
            for (let i = 0; i < binaryStr.length; i++) {
                bytes[i] = binaryStr.charCodeAt(i);
            }
            this._ttsAudioChunks.push(bytes);
        } else if (data.command === "tts_complete") {
            if (this._ttsAudioChunks.length > 0) {
                const blob = new Blob(this._ttsAudioChunks, { type: 'audio/wav' });
                const url = URL.createObjectURL(blob);
                this._ttsAudioChunks = []; // reset

                // Stop any currently playing audio before setting new source
                this._ttsAudioPlayer.pause();
                this._ttsAudioPlayer.currentTime = 0;
                // Note: we do NOT revokeObjectURL here because replay buttons retain references to past blob URLs
                this._ttsAudioPlayer.src = url;
                this._ttsAudioPlayer.play().catch(e => this.callbacks.onLog(`TTS Autoplay blocked: ${e}`, 'warn'));

                // Notify the UI so it can attach a replay button
                this.callbacks.onTTSReady(url);

                // Synergize LipSync magically
                if (this.avatar) {
                    this.avatar.connectAudio(this._ttsAudioPlayer);
                }
            }
        }
    }

    // --- Utils ---
    _blobToBase64(blob) {
        return new Promise((resolve, _) => {
            const reader = new FileReader();
            reader.onloadend = () => resolve(reader.result);
            reader.readAsDataURL(blob);
        });
    }
}
