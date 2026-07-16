# Unreal Engine Integration Guide: Open Virtual Agent Research Platform (OVARP)

> **Target Engine Version:** Unreal Engine 5.5+ (tested with UE 5.7)

This guide provides everything an Unreal Engine developer needs to connect a 3D XR, desktop, or VR application to the OVARP Server.

OVARP acts as the "brain," handling Speech-to-Text (STT), Large Language Model (LLM) processing, and Text-to-Speech (TTS) synthesis. Unreal Engine acts as the "body," handling user microphone input, 3D rendering, avatar animation, and spatial interaction.

---

## 1. Connection Protocols

The OVARP Server supports two concurrent protocols. You only need to implement **one**.

### Option A: WebSockets (Recommended)

Best for most projects, including Meta Quest, PCVR, and desktop applications. UE5 has built-in WebSocket support.

- **URL**: `ws://<server_ip>:8000/ws/client/<your_client_id>`
  - *Example*: `ws://192.168.1.100:8000/ws/client/unreal_vr_01`
- **UE5 Module**: Add `"WebSockets"` to your `Build.cs` file.

**Build.cs Setup:**
```csharp
PublicDependencyModuleNames.AddRange(new string[] {
    "Core", "CoreUObject", "Engine", "InputCore",
    "WebSockets", "Json", "JsonUtilities"
});
```

### Option B: ZeroMQ (Low-Latency PCVR)

Best for ultra-low-latency desktop VR running on the same network or local machine.

- **PUB/SUB Port**: `tcp://<server_ip>:5555` (Subscribe to receive commands from the server).
  - *Note*: You MUST subscribe to your specific `device_id` AND the `"all"` topic.
- **REQ/REP Port**: `tcp://<server_ip>:5556` (Send requests to the server).
- **UE5 Plugin**: Use a third-party ZeroMQ integration such as [UE4-ZMQ](https://github.com/niclastr/ue4-zmq) (compatible with UE5) or compile [libzmq](https://github.com/zeromq/libzmq) as a third-party library.

> **Note:** For most projects, WebSockets provide low-enough latency. Use ZeroMQ only if you measure that WebSocket overhead is a bottleneck for your specific use case.

---

## 2. Universal Payload Structure

Every message sent to or received from the OVARP Server uses a strict JSON schema called `BaseCommand`.

```json
{
  "sender": "unreal_vr_01",
  "target_device": "server",
  "target_agent": "agent_alpha",
  "command_type": "audio",
  "command": "stt_request",
  "subcommand": {
    "key": "value"
  }
}
```

> **Important Configuration Note:**
> The values for `sender`, `target_device`, and `target_agent` MUST match the IDs declared in the server's `config.yaml`. Default IDs are:
> - Devices: `quest_vr_01`, `quest_vr_02`, `woz_console`
> - Agents: `agent_alpha`, `agent_beta`
>
> Add your Unreal client as a new device entry in `config.yaml`:
> ```yaml
> devices:
>   - id: "unreal_vr_01"
>     name: "Unreal VR Client"
>     type: "xr"
> ```

---

## 3. WebSocket Client Implementation (C++)

### OVARPWebSocket.h

```cpp
#pragma once

#include "CoreMinimal.h"
#include "IWebSocket.h"
#include "GameFramework/Actor.h"
#include "OVARPWebSocket.generated.h"

DECLARE_DYNAMIC_MULTICAST_DELEGATE_TwoParams(FOnAgentReply, const FString&, Text, const FString&, RawJson);
DECLARE_DYNAMIC_MULTICAST_DELEGATE_TwoParams(FOnAgentAction, const FString&, Emotion, const FString&, Animation);
DECLARE_DYNAMIC_MULTICAST_DELEGATE_OneParam(FOnTTSChunk, const TArray<uint8>&, AudioData);
DECLARE_DYNAMIC_MULTICAST_DELEGATE(FOnTTSComplete);

UCLASS()
class MYPROJECT_API AOVARPWebSocket : public AActor
{
    GENERATED_BODY()

public:
    AOVARPWebSocket();

    UPROPERTY(EditAnywhere, Category = "OVARP")
    FString ServerUrl = TEXT("ws://192.168.1.100:8000/ws/client/unreal_vr_01");

    UPROPERTY(EditAnywhere, Category = "OVARP")
    FString DeviceId = TEXT("unreal_vr_01");

    UPROPERTY(EditAnywhere, Category = "OVARP")
    FString AgentId = TEXT("agent_alpha");

    // Events
    UPROPERTY(BlueprintAssignable, Category = "OVARP")
    FOnAgentReply OnAgentReply;

    UPROPERTY(BlueprintAssignable, Category = "OVARP")
    FOnAgentAction OnAgentAction;

    UPROPERTY(BlueprintAssignable, Category = "OVARP")
    FOnTTSChunk OnTTSChunk;

    UPROPERTY(BlueprintAssignable, Category = "OVARP")
    FOnTTSComplete OnTTSComplete;

    UFUNCTION(BlueprintCallable, Category = "OVARP")
    void Connect();

    UFUNCTION(BlueprintCallable, Category = "OVARP")
    void Disconnect();

    UFUNCTION(BlueprintCallable, Category = "OVARP")
    void SendTextToLLM(const FString& Text);

    UFUNCTION(BlueprintCallable, Category = "OVARP")
    void SendAudioToSTT(const TArray<uint8>& AudioData);

protected:
    virtual void BeginPlay() override;
    virtual void EndPlay(const EEndPlayReason::Type EndPlayReason) override;

private:
    TSharedPtr<IWebSocket> WebSocket;

    void OnConnected();
    void OnConnectionError(const FString& Error);
    void OnClosed(int32 StatusCode, const FString& Reason, bool bWasClean);
    void OnMessage(const FString& Message);

    void SendCommand(const FString& CommandType, const FString& Command,
                     TSharedPtr<FJsonObject> Subcommand);
};
```

### OVARPWebSocket.cpp

```cpp
#include "OVARPWebSocket.h"
#include "WebSocketsModule.h"
#include "IWebSocket.h"
#include "Json.h"
#include "Misc/Base64.h"

AOVARPWebSocket::AOVARPWebSocket()
{
    PrimaryActorTick.bCanEverTick = false;
}

void AOVARPWebSocket::BeginPlay()
{
    Super::BeginPlay();

    // Ensure the WebSockets module is loaded
    FModuleManager::Get().LoadModuleChecked<FWebSocketsModule>("WebSockets");
}

void AOVARPWebSocket::EndPlay(const EEndPlayReason::Type EndPlayReason)
{
    Disconnect();
    Super::EndPlay(EndPlayReason);
}

void AOVARPWebSocket::Connect()
{
    if (WebSocket.IsValid() && WebSocket->IsConnected())
    {
        return;
    }

    WebSocket = FWebSocketsModule::Get().CreateWebSocket(ServerUrl, TEXT("ws"));

    WebSocket->OnConnected().AddUObject(this, &AOVARPWebSocket::OnConnected);
    WebSocket->OnConnectionError().AddUObject(this, &AOVARPWebSocket::OnConnectionError);
    WebSocket->OnClosed().AddUObject(this, &AOVARPWebSocket::OnClosed);
    WebSocket->OnMessage().AddUObject(this, &AOVARPWebSocket::OnMessage);

    WebSocket->Connect();
}

void AOVARPWebSocket::Disconnect()
{
    if (WebSocket.IsValid())
    {
        WebSocket->Close();
        WebSocket.Reset();
    }
}

void AOVARPWebSocket::OnConnected()
{
    UE_LOG(LogTemp, Log, TEXT("OVARP: Connected to server"));
}

void AOVARPWebSocket::OnConnectionError(const FString& Error)
{
    UE_LOG(LogTemp, Error, TEXT("OVARP: Connection error — %s"), *Error);
}

void AOVARPWebSocket::OnClosed(int32 StatusCode, const FString& Reason, bool bWasClean)
{
    UE_LOG(LogTemp, Warning, TEXT("OVARP: Disconnected (code=%d, reason=%s)"), StatusCode, *Reason);
}

void AOVARPWebSocket::OnMessage(const FString& Message)
{
    TSharedPtr<FJsonObject> JsonObject;
    TSharedRef<TJsonReader<>> Reader = TJsonReaderFactory<>::Create(Message);

    if (!FJsonSerializer::Deserialize(Reader, JsonObject) || !JsonObject.IsValid())
    {
        UE_LOG(LogTemp, Error, TEXT("OVARP: Failed to parse incoming JSON"));
        return;
    }

    // WS transport wraps messages in {"topic": "...", "payload": {...}}
    TSharedPtr<FJsonObject> Data = JsonObject->HasField(TEXT("payload"))
        ? JsonObject->GetObjectField(TEXT("payload"))
        : JsonObject;

    FString CommandType = Data->GetStringField(TEXT("command_type"));
    FString Command = Data->GetStringField(TEXT("command"));

    // --- Handle TTS Audio ---
    if (CommandType == TEXT("audio") && Command == TEXT("tts_chunk"))
    {
        FString Base64Audio = Data->GetObjectField(TEXT("subcommand"))->GetStringField(TEXT("audio_base64"));
        TArray<uint8> AudioBytes;
        FBase64::Decode(Base64Audio, AudioBytes);
        OnTTSChunk.Broadcast(AudioBytes);
        return;
    }
    if (CommandType == TEXT("audio") && Command == TEXT("tts_complete"))
    {
        OnTTSComplete.Broadcast();
        return;
    }

    // --- Handle LLM Reply ---
    if (CommandType == TEXT("message") && Command == TEXT("llm_reply"))
    {
        TSharedPtr<FJsonObject> Sub = Data->GetObjectField(TEXT("subcommand"));
        FString ReplyText = Sub->GetStringField(TEXT("text"));
        OnAgentReply.Broadcast(ReplyText, Message);
        return;
    }

    // --- Handle Agent Actions (emotions, animations) ---
    if (CommandType == TEXT("action") && Command == TEXT("execute_state"))
    {
        TSharedPtr<FJsonObject> Sub = Data->GetObjectField(TEXT("subcommand"));
        FString Emotion = Sub->HasField(TEXT("emotions"))
            ? Sub->GetStringField(TEXT("emotions")) : TEXT("");
        FString Animation = Sub->HasField(TEXT("actions"))
            ? Sub->GetStringField(TEXT("actions")) : TEXT("");
        OnAgentAction.Broadcast(Emotion, Animation);
        return;
    }
}

void AOVARPWebSocket::SendCommand(const FString& CommandType, const FString& Command,
                                  TSharedPtr<FJsonObject> Subcommand)
{
    if (!WebSocket.IsValid() || !WebSocket->IsConnected())
    {
        UE_LOG(LogTemp, Warning, TEXT("OVARP: Cannot send — not connected"));
        return;
    }

    TSharedPtr<FJsonObject> Payload = MakeShareable(new FJsonObject());
    Payload->SetStringField(TEXT("sender"), DeviceId);
    Payload->SetStringField(TEXT("target_device"), TEXT("server"));
    Payload->SetStringField(TEXT("target_agent"), AgentId);
    Payload->SetStringField(TEXT("command_type"), CommandType);
    Payload->SetStringField(TEXT("command"), Command);
    if (Subcommand.IsValid())
    {
        Payload->SetObjectField(TEXT("subcommand"), Subcommand);
    }

    FString OutputString;
    TSharedRef<TJsonWriter<>> Writer = TJsonWriterFactory<>::Create(&OutputString);
    FJsonSerializer::Serialize(Payload.ToSharedRef(), Writer);

    WebSocket->Send(OutputString);
}

void AOVARPWebSocket::SendTextToLLM(const FString& Text)
{
    TSharedPtr<FJsonObject> Sub = MakeShareable(new FJsonObject());
    Sub->SetStringField(TEXT("text"), Text);
    SendCommand(TEXT("message"), TEXT("llm_request"), Sub);
}

void AOVARPWebSocket::SendAudioToSTT(const TArray<uint8>& AudioData)
{
    FString Base64Audio = FBase64::Encode(AudioData);
    TSharedPtr<FJsonObject> Sub = MakeShareable(new FJsonObject());
    Sub->SetStringField(TEXT("audio_base64"), Base64Audio);
    SendCommand(TEXT("audio"), TEXT("stt_request"), Sub);
}
```

---

## 4. Core Workflows

### A. Sending Voice (Microphone to STT)

Record the user's microphone using Unreal's audio capture system, encode as WAV/Base64, and send:

1. Use `UAudioCaptureComponent` or the platform's native mic API.
2. Convert captured PCM data to a WAV byte array.
3. Base64-encode the bytes.
4. Call `SendAudioToSTT(AudioBytes)`.

### B. Sending Text (Direct LLM Request)

If you have an in-world keyboard or debug UI:

```cpp
OVARPClient->SendTextToLLM(TEXT("Hello, how are you today?"));
```

### C. Receiving Agent Audio Responses (TTS)

Bind to the `OnTTSChunk` and `OnTTSComplete` delegates to buffer and play audio:

```cpp
// In your setup:
OVARPClient->OnTTSChunk.AddDynamic(this, &AMyActor::HandleTTSChunk);
OVARPClient->OnTTSComplete.AddDynamic(this, &AMyActor::HandleTTSComplete);

void AMyActor::HandleTTSChunk(const TArray<uint8>& AudioData)
{
    // Append to audio buffer
    AudioBuffer.Append(AudioData);
}

void AMyActor::HandleTTSComplete()
{
    // Create a USoundWave from the buffered bytes and play it
    // Use ImportedSoundWave or a runtime audio library
    PlayBufferedAudio(AudioBuffer);
    AudioBuffer.Empty();
}
```

> **Note:** For runtime WAV playback, consider the [RuntimeAudioImporter](https://fab.com/s/f8a3609fa51d) plugin, which can decode WAV/MP3 bytes into `USoundWave` objects at runtime.

### D. Receiving Agent Actions (Emotions & Body Language)

Bind to `OnAgentAction` to trigger animations and facial expressions:

```cpp
OVARPClient->OnAgentAction.AddDynamic(this, &AMyActor::HandleAgentAction);

void AMyActor::HandleAgentAction(const FString& Emotion, const FString& Animation)
{
    if (!Emotion.IsEmpty())
    {
        // Trigger facial expression blend shapes
        // e.g., SetMorphTarget or drive an Animation Blueprint variable
        SetFacialExpression(Emotion);
    }
    if (!Animation.IsEmpty())
    {
        // Trigger animation montage
        PlayAnimationMontage(Animation);
    }
}
```

---

## 5. XR Telemetry Ingest

OVARP provides a dedicated REST endpoint for streaming XR tracking data from headsets. Use Unreal's `FHttpModule` to send batched telemetry:

### Endpoint

`POST /api/xr/telemetry`

### Implementation

```cpp
#include "HttpModule.h"
#include "Interfaces/IHttpRequest.h"
#include "Interfaces/IHttpResponse.h"

void UOVARPTelemetry::SendTelemetryBatch(const FString& ServerUrl, const FString& DeviceId)
{
    // Build the JSON payload
    TSharedPtr<FJsonObject> Payload = MakeShareable(new FJsonObject());
    Payload->SetStringField(TEXT("device_id"), DeviceId);

    TArray<TSharedPtr<FJsonValue>> FramesArray;

    // Capture current tracking data
    TSharedPtr<FJsonObject> Frame = MakeShareable(new FJsonObject());
    Frame->SetNumberField(TEXT("timestamp"), FPlatformTime::Seconds());

    FVector HeadPos = GetHeadPosition(); // Your tracking function
    FQuat HeadRot = GetHeadRotation();

    TSharedPtr<FJsonObject> Pos = MakeShareable(new FJsonObject());
    Pos->SetNumberField(TEXT("x"), HeadPos.X);
    Pos->SetNumberField(TEXT("y"), HeadPos.Y);
    Pos->SetNumberField(TEXT("z"), HeadPos.Z);
    Frame->SetObjectField(TEXT("head_position"), Pos);

    FramesArray.Add(MakeShareable(new FJsonValueObject(Frame)));
    Payload->SetArrayField(TEXT("frames"), FramesArray);

    // Serialize and send
    FString OutputString;
    TSharedRef<TJsonWriter<>> Writer = TJsonWriterFactory<>::Create(&OutputString);
    FJsonSerializer::Serialize(Payload.ToSharedRef(), Writer);

    TSharedRef<IHttpRequest> Request = FHttpModule::Get().CreateRequest();
    Request->SetURL(FString::Printf(TEXT("%s/api/xr/telemetry"), *ServerUrl));
    Request->SetVerb(TEXT("POST"));
    Request->SetHeader(TEXT("Content-Type"), TEXT("application/json"));
    Request->SetContentAsString(OutputString);
    Request->ProcessRequest();
}
```

> **Tip:** Call `SendTelemetryBatch` on a timer (e.g., every 200ms) rather than every frame.

---

## 6. Session Management (REST API)

Your Unreal client can programmatically manage experiment sessions via HTTP.

| Method | Endpoint | Purpose |
|--------|----------|---------|
| `GET`  | `/api/session/status` | Get current session state |
| `POST` | `/api/session/start`  | Start session (`{"participant_id": "P001"}`) |
| `POST` | `/api/session/pause`  | Pause active session |
| `POST` | `/api/session/resume` | Resume paused session |
| `POST` | `/api/session/end`    | End session and retrieve data |
| `POST` | `/api/session/marker` | Add event marker (`{"label": "task_start"}`) |

### Example: HTTP POST Helper

```cpp
void UOVARPHttp::PostJson(const FString& Url, const FString& JsonBody)
{
    TSharedRef<IHttpRequest> Request = FHttpModule::Get().CreateRequest();
    Request->SetURL(Url);
    Request->SetVerb(TEXT("POST"));
    Request->SetHeader(TEXT("Content-Type"), TEXT("application/json"));
    Request->SetContentAsString(JsonBody);
    Request->OnProcessRequestComplete().BindLambda(
        [](FHttpRequestPtr Req, FHttpResponsePtr Res, bool bSuccess)
        {
            if (bSuccess && Res.IsValid())
            {
                UE_LOG(LogTemp, Log, TEXT("OVARP HTTP: %s"), *Res->GetContentAsString());
            }
        });
    Request->ProcessRequest();
}

// Usage:
PostJson(TEXT("http://192.168.1.100:8000/api/session/start"),
         TEXT("{\"participant_id\": \"P001\"}"));

PostJson(TEXT("http://192.168.1.100:8000/api/session/marker"),
         TEXT("{\"label\": \"task_phase_2\"}"));
```

---

## 7. Agent Profiles (REST API)

Profiles are rich persona definitions that can be applied at runtime to switch agent behavior, voice, and appearance.

| Method | Endpoint | Purpose |
|--------|----------|---------|
| `GET`  | `/api/profiles`           | List all profiles |
| `GET`  | `/api/profiles/{id}`      | Get profile details |
| `POST` | `/api/profiles/apply`     | Apply profile to agent |
| `GET`  | `/api/agents/{agent_id}`  | Get agent's current state |

### Example: Applying a Profile

```cpp
PostJson(TEXT("http://192.168.1.100:8000/api/profiles/apply"),
         TEXT("{\"profile_id\": \"therapist_male\", \"agent_id\": \"agent_alpha\"}"));
```

---

## 8. Scaling: Multiple Clients

### Scenario A: Multiple Unreal Clients → ONE Server

1. Add each client as a device in `config.yaml`:
```yaml
devices:
  - id: "unreal_vr_01"
    name: "Station 1"
    type: "xr"
  - id: "unreal_vr_02"
    name: "Station 2"
    type: "xr"
```
2. Each Unreal instance connects with its own `DeviceId`.
3. The server routes messages to the correct client automatically via unicast targeting.

### Scenario B: Load Balancing Across Multiple Servers

Deploy multiple OVARP Server instances and point different Unreal clients to different server IPs. Each server runs independently with its own AI pipeline and conversation state. No special configuration needed.

---

## 9. Recommended Plugins & Resources

| Need | Recommendation |
|------|---------------|
| WebSocket client | Built-in `WebSockets` module (no plugin needed) |
| Runtime audio playback | [RuntimeAudioImporter](https://fab.com/s/f8a3609fa51d) |
| VRM avatar rendering | [VRM4U](https://github.com/ruyo/VRM4U) (UE5 compatible) |
| ZeroMQ (if needed) | [libzmq](https://github.com/zeromq/libzmq) compiled as third-party lib |
| Lip sync | Oculus Lip Sync SDK or OVRLipSync (Meta Quest), or audio-driven blend shapes via `AnalyserNode` equivalent |
| JSON serialization | Built-in `Json` and `JsonUtilities` modules |
