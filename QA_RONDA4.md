# Guía de pruebas — Ronda 4

Esta ronda cierra los 33 cambios que salieron de los reportes 1, 2 y 3 y de la
revisión técnica. Cada punto de abajo dice **qué hacer** y **qué debería pasar**,
y lleva entre paréntesis el número del hallazgo original para que puedas
compararlo con tu reporte anterior.

Si algo no coincide con lo que dice acá, eso es el hallazgo. No hace falta que
investigues la causa.

---

## Antes de empezar

### 1. Levantar el servidor

```bash
cd OVARP-Server
./venv/bin/python -m uvicorn src.main:app --host 0.0.0.0 --port 8000
```

Abrir `http://localhost:8000` y hacer **hard refresh** (Cmd+Shift+R o
Ctrl+Shift+R). Sin eso el navegador sirve la consola vieja y nada de esto aplica.

### 2. Desactivar la traducción automática de Chrome

Debería estar desactivada sola ahora. Si Chrome igual ofrece traducir, decile que
no: en la ronda 2 cambió "Resume" por "Currículum" y los nombres de los botones
dejaron de coincidir con el reporte.

### 3. Chrome bloquea el cliente desplegado contra un servidor local

Si vas a usar el cliente de Vercel (`ovarp-unity-web-client.vercel.app`) contra
un servidor en tu máquina, **Chrome lo bloquea**. En la consola del navegador
aparece:

```
net::ERR_BLOCKED_BY_LOCAL_NETWORK_ACCESS_CHECKS
```

Es una restricción nueva de Chrome: un sitio HTTPS público ya no puede abrir un
socket a `localhost`. Antes funcionaba y la documentación del repo todavía dice
que sí. Dos salidas:

**Opción A (recomendada) — levantar un túnel:**

```bash
cloudflared tunnel --url http://localhost:8000
```

Después poner en el campo *OVARP server* del cliente la URL impresa, cambiando
`https://` por `wss://`.

**Opción B — abrir Chrome con la verificación desactivada.** Solo para probar,
nunca para una sesión con un participante:

```bash
open -na "Google Chrome" --args \
  --disable-features=LocalNetworkAccessChecks,PrivateNetworkAccessChecks
```

Si en vez del cliente de Vercel usás el player local (`http://localhost:8000/player`),
nada de esto aplica: mismo origen, sin bloqueo.

### 4. Compilar el cliente Unity

> **Importante:** hay cambios del cliente posteriores al último build publicado
> (el arreglo del placeholder que se montaba sobre el botón Send). Recompilá y
> volvé a publicar antes del Bloque C, o probalo sabiendo que ese punto fallará.
>
> El resto del código del cliente **no se pudo compilar**
> en la máquina donde se hizo el cambio. Abrí el proyecto en Unity y compilá
> antes de probar el Bloque C. Si no compila, eso es el primer hallazgo y el
> resto del Bloque C queda bloqueado.

---

## Bloque A — Consola WoZ

### A1. La pestaña de control ya no apunta al vacío (R2-1)

1. Abrir el player: botón **OPEN PLAYER** arriba a la derecha.
2. En la consola, ir a **(05) WOZ CONTROL**.

**Esperado:** el selector *Device ID* se pone solo en el cliente que está
conectado (`web_panel_01`), no en `quest_vr_01`. Debajo dice en verde
"web_panel_01 is connected."

3. Cambiar el selector a `quest_vr_01` a mano.

**Esperado:** el texto pasa a ámbar y avisa que no está conectado y que las
acciones enviadas ahí no llegan a ningún lado, más la lista de los que sí están.

### A2. Queda claro qué manda el selector (confusión reportada en la ronda 3)

Mirar la tarjeta **What the Device picker governs**, en la misma columna.

**Esperado:** dice que el selector gobierna **solo** los botones de acción, y que
la voz se difunde a todos los clientes igual. Ese era el punto que confundía:
la emoción no llegaba pero el mensaje sí.

### A3. Audio doble (R2-2)

1. Tener abiertos la consola y el player en la misma computadora.
2. Mandar un mensaje y escuchar.
3. En **(02) LLM PLAYGROUND**, pulsar **Mute Here**.
4. Mandar otro mensaje.

**Esperado:** con Mute activo se escucha una sola vez. El player sigue hablando.
El botón cambia a **Unmute Here**.

### A4. Audios superpuestos (R3-3)

1. Mandar un mensaje largo.
2. Sin esperar a que termine, escribir algo en **Direct TTS** y pulsar **Speak
   This Text**.

**Esperado:** el audio anterior se corta. No se escuchan dos voces encimadas.

### A5. Panel de latencia (R2-11)

En **(02) LLM PLAYGROUND**, mandar un mensaje y mirar los cuatro recuadros
STT / LLM / TTS / Total.

**Esperado:** se llenan con números. Antes quedaban siempre en "—".

### A6. La latencia total incluye la transcripción (R2-9)

Hablar por micrófono (no escribir) y comparar el número de **STT** con el de
**Total**.

**Esperado:** Total es mayor que LLM + TTS, porque ahora suma el STT. Antes el
STT quedaba afuera y había que sumarlo a mano.

### A7. La voz que se muestra es la que suena (R2-8)

1. Ir a **(03) PROFILES** y aplicar un perfil que fije una voz (por ejemplo uno
   con Kore).
2. Volver a **(02) LLM PLAYGROUND** y mirar la línea **Speech** arriba.

**Esperado:** dice la voz del perfil, no la del selector. Mandar un mensaje y
confirmar que suena esa misma voz.

### A8. Marcador sin sesión (R2-3)

Sin iniciar sesión, ir a **(04) STUDY SESSION**, escribir una etiqueta y pulsar
**Mark**.

**Esperado:** aparece un aviso rojo "Not recorded: No active session for
markers". Antes decía que estaba OK y el marcador se perdía sin avisar.

### A9. Exportar marcadores después de terminar (H16, R3-6)

1. Iniciar sesión con un participante.
2. Poner 2 o 3 marcadores.
3. Pulsar **End**.
4. Descargar **Markers CSV** desde **(01) OVERVIEW**.

**Esperado:** el CSV trae los marcadores y el ID del participante. Antes, después
de End, salía `NO_ACTIVE_SESSION` y parecía que se habían perdido.

### A10. Perfiles migrados (R2-12)

Ir a **(03) PROFILES** y mirar la lista.

**Esperado:** los perfiles de condición se llaman "Empathetic" y "Neutral", sin
"(migrated)", y muestran el rol "Experimental condition" en vez de "No role
defined".

### A11. Aplicar perfil a todos los agentes (R2-5)

Aplicar un perfil con **All Agents** seleccionado.

**Esperado:** el perfil se aplica a los dos agentes y **no** aparece ninguna
etiqueta `[avatar: ...]`. En la ronda 2 salían dos por un solo click.

### A12. Botones Replay (R2-13)

Mandar un mensaje que genere una respuesta de varias frases.

**Esperado:** los botones dicen "Replay 1", "Replay 2", etc. Antes eran todos
idénticos.

### A13. Direct TTS y el salto de línea (R2-10)

Escribir `hola` en Direct TTS, dar Enter para dejar un salto de línea al final y
enviar.

**Esperado:** en el chat aparece `hola` limpio, sin el `\n`.

### A14. Favicon (H05)

Mirar la pestaña del navegador en `/`, `/player` y la página de encuesta.

**Esperado:** hay un ícono. No debería haber un 404 de `favicon.ico` en la
consola del navegador.

---

## Bloque B — Seguridad y validación de la API

Se prueba con `curl` desde la terminal. El servidor tiene que estar corriendo.

### B1. Respuestas de encuesta protegidas (H13)

Reiniciar el servidor **con un token**:

```bash
OVARP_ACCESS_TOKEN=secret123 ./venv/bin/python -m uvicorn src.main:app --port 8000
```

```bash
# Sin token: debe dar 401
curl -i -s http://localhost:8000/api/surveys/responses | head -1

# Con token: debe dar 200
curl -i -s -H "X-OVARP-Token: secret123" http://localhost:8000/api/surveys/responses | head -1

# El participante NO necesita token para responder: debe dar 200
curl -i -s http://localhost:8000/api/surveys/sus | head -1
```

**Esperado:** `401`, `200`, `200`. Antes el primero devolvía `200` y cualquiera
podía leer las respuestas y los IDs de los participantes.

### B2. Escenario sin pasos (H11)

```bash
curl -s -X POST http://localhost:8000/api/scenarios \
  -H 'Content-Type: application/json' \
  -d '{"id":"vacio","name":"Vacio","steps":[]}'
```

**Esperado:** error 422 diciendo que hace falta al menos un paso. Antes daba
error 500 del servidor.

### B3. IDs que escriben fuera de la carpeta (H12)

```bash
curl -s -X POST http://localhost:8000/api/scenarios \
  -H 'Content-Type: application/json' \
  -d '{"id":"../../pwned","name":"X","steps":[{"id":"s1","instruction":"x"}]}'
```

**Esperado:** error 422. Y confirmar que **no** se creó ningún archivo fuera de
`scenarios/`.

### B4. Respuestas de encuesta fuera de escala (H15)

```bash
curl -i -s -X POST http://localhost:8000/api/surveys/response \
  -H 'Content-Type: application/json' \
  -d '{"survey_id":"sus","participant_id":"QA","answers":{"sus_1":99}}' | head -1
```

**Esperado:** `422`. La escala del SUS es 1 a 5; con 99 se podían producir
puntajes mayores a 100.

### B5. Key de OpenAI tipo placeholder (R3-4, R1-3)

Con la key de OpenAI todavía en `sk-...` en el `.env`, mirar los badges de
proveedor en **(02) LLM PLAYGROUND**.

**Esperado:** OpenAI aparece en rojo/error, no como "ready". Antes decía que
estaba lista y no lo estaba.

Después, para cerrar el hallazgo de verdad: ir a **(07) API KEY STORE**, pegar
una key real de OpenAI, pulsar **Save to the key store** y confirmar que el badge
pasa a verde **sin reiniciar el servidor**.

---

## Bloque C — Cliente Unity

Requiere compilar el proyecto primero (ver *Antes de empezar*, punto 4).

### C1. El avatar reacciona a lo que genera el agente (R3-1, R2-1)

Este es el cambio más importante de la ronda.

1. Conectar el web client.
2. Desde la consola, en **(02) LLM PLAYGROUND**, conversar normalmente con el
   agente (no usar los botones de WoZ todavía).

**Esperado:** el avatar cambia de expresión y hace gestos durante las respuestas.

> Por qué fallaba: el cliente recibía las cinco categorías juntas (emoción,
> gesto, mirada, movimiento) pero solo procesaba la primera. Nunca fue que
> faltara implementarlo.

### C2. Los botones de WoZ llegan al avatar (R2-1)

Con el Device ID puesto en el cliente conectado (ver A1), pulsar emociones y
acciones desde **(05) WOZ CONTROL**.

**Esperado:** el avatar responde a cada una.

### C3. Saltos de línea y texto cortado (R2-4, H09)

Pedirle al agente una respuesta larga y con varios párrafos. Si se puede, pedirle
que use comillas.

**Esperado:** los saltos de línea se ven como saltos, no como `\n\n` escrito. La
respuesta no se corta a la mitad al aparecer una comilla.

### C4. Grabar dos veces seguidas (H07)

1. Mantener Space (o el círculo) y hablar. Soltar.
2. Esperar la respuesta.
3. Volver a mantener Space y hablar de nuevo.

**Esperado:** la segunda grabación funciona. Antes fallaba siempre.

### C5. Errores del servidor visibles (H08)

Provocar un fallo del proveedor: en **(07) API KEY STORE**, borrar la key de
Gemini con **Clear**, y después mandar un mensaje desde el cliente.

**Esperado:** el chat dice que algo falló y vuelve a aceptar mensajes. Antes se
quedaba en "…" para siempre.

Acordate de volver a poner la key después.

### C6. Instrucciones de uso (R2-7, H01)

Mirar el cuadro de texto del chat con el campo vacío.

**Esperado:** dice "Type a message, or hold Space / the circle to talk".

### C7. Estado del servidor (feedback interno)

Mirar arriba del chat.

**Esperado:** hay una línea que dice si está conectado o no.

### C8. El botón Send (R2-6)

Escribir un mensaje largo en el campo de texto.

**Esperado:** el botón **Send** sigue visible. Antes se salía del borde derecho.

### C9. Ocultar el chat (H03)

Pulsar **Hide Chat**.

**Esperado:** desaparece el panel entero, incluido el fondo blanco, y el botón
pasa a decir **Show Chat**. Pulsarlo de nuevo lo trae de vuelta.

### C10. Inicio de la conversación (H04)

Subir con el scroll hasta arriba del todo en el chat.

**Esperado:** aparece "Start of the conversation" y no se puede seguir subiendo
indefinidamente.

---

## Lo que NO cambió

No hace falta probar esto, ya sabemos que sigue igual:

- **No hay cambio de avatar.** En **(05) WOZ CONTROL** no debería aparecer
  ninguna fila **AVATAR**: hay una sola apariencia, así que no se ofrece un
  control para cambiarla. Tampoco deberían salir etiquetas `[avatar: default]`
  colgando de las respuestas del agente. Si ves cualquiera de las dos cosas,
  eso sí es un hallazgo.
- **Latencia español vs inglés.** No se tocó. Ahora es medible con el panel de
  latencia (A5), pero hace falta una medición formal con varios turnos de cada
  idioma.
- **El escenario que saltó al paso 2** en la ronda 2 no se pudo reproducir, así
  que no se arregló nada ahí. Si vuelve a pasar, anotá los pasos exactos.

---

## Cómo reportar

Para cada punto que falle, anotá:

1. El código del punto (por ejemplo `A7` o `C4`).
2. Qué hiciste, en orden.
3. Qué pasó, comparado con el "Esperado".
4. Captura si es visual, o el texto del log si es de consola.

Los logs del servidor salen por la terminal donde corre `uvicorn`. Los del
navegador están en **(08) SYSTEM LOGS**, que ahora tiene filtro por nivel,
búsqueda y **Export** a CSV: si algo falla, exportá el CSV y adjuntalo.
