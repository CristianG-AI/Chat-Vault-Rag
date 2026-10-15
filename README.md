# 💬 VaultChat — chat with your own notes

**Point it at your Obsidian vault and ask it anything.** Answers come back grounded
in *your* notes — with a link to the exact note and section. It runs on your machine,
with your own API keys. If the answer isn't in your notes, it says so instead of
making something up.

> Local-first · open source · cites every source · measured to not hallucinate.

**[▶ Try the live demo](https://chat-vault-demo.streamlit.app/)** (no setup) · **[📬 Join the waitlist](https://cristiang-ai.github.io/Chat-Vault-Rag/)** for a hosted version

**Measured on the author's vault** (open evals harness, 15 golden questions, LLM-judged):

| recall@8 | groundedness | fact coverage | out-of-scope abstention | cost/query |
|:---:|:---:|:---:|:---:|:---:|
| **100%** | **100%** | **97%** | **100%** | **~$0.02** |

Stack: Python · ChromaDB · OpenAI embeddings · Claude · Streamlit.

---

## Quickstart — your vault in ~5 minutes

```bash
# 1. clone & install
git clone https://github.com/CristianG-AI/Chat-Vault-Rag.git
cd Chat-Vault-Rag
python -m venv .venv
.venv\Scripts\Activate.ps1          # Windows PowerShell  (mac/Linux: source .venv/bin/activate)
pip install -r requirements.txt

# 2. configure — copy the template and fill in your vault path + API keys
copy .env.example .env              # mac/Linux: cp .env.example .env
#   VAULT_PATH=C:/path/to/your/vault
#   OPENAI_API_KEY=sk-...           (embeddings)   https://platform.openai.com/api-keys
#   ANTHROPIC_API_KEY=sk-ant-...    (answers)      https://console.anthropic.com/settings/keys

# 3. build the index (chunk → embed → store). Indexing a vault costs a few cents.
python chunk_vault.py
python embed_chunks.py
python build_index.py

# 4. chat
streamlit run app.py                # or one-shot from the CLI:  python ask.py "your question"
```

That's it. All settings (vault path, folders to skip, models, retrieval depth) live
in **`config.py`** and can be overridden from `.env` — you never edit the same value
in three files. Your notes and keys never leave your machine: the only external calls
are to the embedding/LLM providers *you* configure.

> **Repo design note:** the **code lives here**, separate from your vault. Your vault
> is the *data*; this repo is the *code*. Keeping them apart means Obsidian doesn't
> index Python files and the repo stays clean.

---

## How it works

`question → embedding (OpenAI) → Chroma similarity search → top-k of YOUR chunks →
Claude → answer with [n] citations`. Each retrieved chunk carries its source note and
heading, so every claim is traceable back to where it came from.

---

> The sections below document the design decisions behind each step (parts in
> Spanish — kept as the original build log / portfolio notes).

## Pipeline

| Paso | Qué hace | Estado |
|------|----------|--------|
| 1 | **Chunking** — partir las notas en fragmentos (`chunk_vault.py`) | ✅ |
| 2 | **Embeddings** de cada chunk (`embed_chunks.py`) | ✅ |
| 3 | **Vector DB** — cargar en Chroma (`build_index.py`) | ✅ |
| 4 | **Retrieval** — recuperar los chunks de un query (`search.py`) | ✅ |
| 5 | Generación — query + chunks → Claude → respuesta con citas (`ask.py`) | ✅ |
| 6 | Interfaz (Streamlit) — `app.py` | ✅ |
| 7a | **Evals** — golden dataset + juez LLM (`run_evals.py`) | ✅ |
| 7b | Repo público en GitHub | ✅ |
| 7c | **Deploy** — demo pública en Streamlit Cloud | ✅ |

## Paso 1 — Chunking

```bash
python chunk_vault.py "C:\path\to\your\vault"
```

Lee todos los `.md` del vault, los parte en chunks y los guarda en `chunks.jsonl`
(una línea JSON por chunk). Sin API keys. También puedes configurar `VAULT_PATH`
en `.env` o como variable de entorno y ejecutar `python chunk_vault.py`.

### Decisiones de chunking (el *por qué*)

- **Tamaño objetivo: ~1000 caracteres (~250 tokens).** Suficientemente pequeño
  para que cada chunk sea un pasaje enfocado (mejores embeddings, citas precisas);
  suficientemente grande para que se sostenga solo. Las notas de concepto son
  atómicas, así que muchas entran en 1-2 chunks.
- **Chunking consciente de encabezados.** Primero se parte por headers markdown
  (`#`, `##`, …) llevando el rastro de la jerarquía. Así cada chunk sabe a qué
  sección pertenece, y eso se usa para citar la fuente.
- **Overlap de 150 chars.** Arrastra contexto entre chunks vecinos para no cortar
  una idea en la frontera.
- **Se omiten:** `.obsidian`, `.trash`, `copilot` (logs de plugin) y
  `05 - Templates` (sintaxis de plantilla, no conocimiento).

> Estos valores son para **experimentar**: cambia `TARGET_CHARS` / `OVERLAP_CHARS`
> arriba en `chunk_vault.py` y vuelve a correr para ver cómo cambia la distribución.

## Paso 2 — Embeddings

```bash
# 1. (una vez) crear entorno virtual e instalar dependencias
python -m venv .venv
.venv\Scripts\Activate.ps1        # PowerShell (Windows)
pip install -r requirements.txt

# 2. configurar la API key
copy .env.example .env             # luego pega tu OPENAI_API_KEY en .env

# 3. correr
python embed_chunks.py
```

Lee `chunks.jsonl`, genera un embedding por chunk y guarda todo en
`chunks_embedded.jsonl` (lo consume el Paso 3).

### ⚠️ Anthropic no tiene API de embeddings

Claude (Anthropic) se usa para **generar la respuesta** (Paso 5), no para embeber.
Los embeddings necesitan otro proveedor. Decisiones:

- **Proveedor elegido: OpenAI `text-embedding-3-small`** (1536 dims). Es lo que usa
  el curso de DeepLearning.AI, el string del modelo es estable, y embeber todo el
  vault cuesta **~$0.002**.
- **Alternativa recomendada por Anthropic: Voyage AI** (`voyageai`, tiene free tier).
  Para cambiar: `pip install voyageai`, y en `embed_chunks.py` reemplazar el cliente
  de OpenAI por `voyageai.Client().embed(batch, model="voyage-3", input_type="document")`.
- **Alternativa gratis/local:** `sentence-transformers` (corre sin API key), pero es
  una dependencia pesada (torch) y arriesgada en Python 3.14.

### Decisiones de embeddings (el *por qué*)

- **Se antepone `title` + `heading` al texto del chunk** antes de embeber
  (ej. `"RAG — Embeddings\n\n<texto>"`). Así el vector captura también el contexto
  de *dónde vive* el fragmento → mejor recuperación. (Era la idea anotada en el Paso 1.)
- **Lotes de 100** chunks por llamada → ~11 requests en lugar de 1063.
- El `.env` con la key **nunca** se sube a git (está en `.gitignore`).

## Paso 5 — Generación con Claude

```bash
python ask.py "qué es overfitting y cómo lo evito"
```

Cierra el loop RAG completo: la pregunta pasa por el retrieval del Paso 4
(`ask.py` importa `search()`), los top-5 chunks se numeran como fragmentos
`[1]..[5]`, y Claude responde **citando** la fuente de cada afirmación.
Al final imprime las fuentes (nota › sección) y el costo de la pregunta.

Requiere una `ANTHROPIC_API_KEY` real en `.env` (se crea en
https://console.anthropic.com → API keys). Es una key *distinta* a la de
OpenAI: aquí OpenAI embebe, Claude genera.

### Decisiones de generación (el *por qué*)

- **Modelo: `claude-opus-4-8`** — el Opus actual. Para un portfolio piece lo
  que importa es la calidad de la respuesta con citas, no ahorrar centavos;
  una pregunta típica cuesta ~$0.01-0.03.
- **Streaming** — la respuesta se imprime según llega (mejor UX en CLI, y es
  exactamente lo que Streamlit necesitará en el Paso 6 vía el callback `on_text`).
- **System prompt FIJO** — sin fechas ni nada dinámico interpolado. Razón:
  el prompt caching de Anthropic es un *prefix match*; un system prompt
  estable se vuelve cacheable cuando haya conversación multi-turno.
- **Adaptive thinking** (`thinking: {type: "adaptive"}`) — Claude decide
  cuándo y cuánto razonar. Es el modo recomendado en los modelos 4.6+
  (el viejo `budget_tokens` ya no existe en Opus 4.7+).
- **"Responde SOLO del contexto"** — la regla anti-alucinación central de RAG.
  Si los chunks no contienen la respuesta, el sistema lo dice en vez de inventar.
  Esto es lo que harán medible los evals del Paso 7 (groundedness).
- **Citas numeradas `[n]`** — cada n mapea a un chunk recuperado con su nota
  y sección de origen → trazabilidad total de cada afirmación.

## Paso 6 — Interfaz de chat (Streamlit)

```bash
streamlit run app.py
```

Chat en el navegador sobre el mismo loop del Paso 5: `app.py` importa `ask()`
y nada más — toda la lógica RAG vive en un solo lugar.

### Decisiones de interfaz (el *por qué*)

- **`app.py` no sabe nada de RAG.** Solo llama `ask()` y dibuja. Si mañana
  cambia el modelo, el top-k o el prompt, la UI no se toca. (Separación de
  capas: pipeline ≠ presentación.)
- **El streaming se reusa tal cual:** el callback `on_text` que el CLI usa
  para imprimir es el mismo que la UI usa para actualizar un `st.empty()`
  placeholder con cursor `▌`. Diseñar el Paso 5 con callback pagó aquí.
- **El modelo mental de Streamlit:** re-ejecuta TODO el script en cada
  interacción. Por eso el historial vive en `st.session_state` y el último
  turno termina con `st.rerun()` (refresca historial + métricas del sidebar).
- **Fuentes en un expander por respuesta** — la trazabilidad [n] → nota ›
  sección sin ensuciar el chat.
- **Costo visible** — el sidebar acumula el costo real de la sesión
  (sale del `usage` que ya devuelve `ask()`). Un portfolio piece que muestra
  sus propios costos demuestra conciencia de producción.
- **v1 es single-turn a propósito:** cada pregunta es independiente (no se
  envía historial a Claude). Multi-turno con prompt caching es mejora futura.

## Paso 7a — La capa de evals

```bash
copy evals\golden.example.jsonl evals\golden.jsonl
python run_evals.py --retrieval   # solo retrieval — casi gratis (solo embeddings)
python run_evals.py               # completo — genera + juzga (~$0.50 el run)
```

**Golden dataset**: el repo incluye `evals/golden.example.jsonl` como ejemplo
sintético. Para correr evals, cópialo a `evals/golden.jsonl` o crea tu propio
dataset local. `evals/golden.jsonl` y `evals/results/*.json` están ignorados
para evitar publicar datos del corpus o resultados generados.

### Métricas de referencia (2026-06-09, k=8)

| Métrica | Valor |
|---------|-------|
| recall@8 (¿nota correcta en el top-k?) | **100%** (11/11) · MRR 0.955 |
| Groundedness (¿todo sale del contexto?) | **100%** |
| Citas `[n]` presentes | **100%** |
| Cobertura de hechos clave | **97%** |
| Abstención en preguntas fuera del vault | **100%** (4/4) |
| Latencia media | ~8.6 s |
| Costo medio por pregunta | ~$0.019 |

### La historia de iteración (por qué los evals valen)

1. **Run 1** (k=5): hechos 86%. Dos preguntas débiles quedaron con cobertura parcial.
2. **Hipótesis A — el prompt:** "sé conciso" recorta cobertura. Se cambió a
   "directo pero completo" y se re-corrió → **86% igual**. El prompt no era el
   cuello de botella (el cambio se quedó: respuestas más completas en general).
3. **Diagnóstico real:** recall@5 *por nota* era 100%, pero los chunks con los
   hechos vivían en **rank 6-7** — el top-5 traía otras secciones de la nota
   correcta. *Recall por fuente ≠ recall por hecho.*
4. **Run 3** (k=5 → 8): hechos **86% → 97%**. Trade-off medido: +0.7s de
   latencia, +$0.004/pregunta.

> Sin evals, el paso 2 se habría "sentido" como una mejora y el verdadero
> problema (granularidad de retrieval) habría seguido invisible.

### Decisiones de evals (el *por qué*)

- **Golden hecho a mano, no generado:** preguntas escritas leyendo el corpus.
  Es defendible ("sé exactamente qué mide") y obliga a conocer los datos.
- **LLM-as-judge con structured outputs:** el juez (Claude) devuelve un
  `Veredicto` Pydantic validado — booleans e índices, no prosa que parsear.
- **Lo determinista se mide sin juez:** citas `[n]` se verifican con regex local;
  el juez solo evalúa lo que requiere juicio (groundedness, cobertura, abstención).
- **Match de fuentes por substring** — robusto a acentos/encodings en rutas.
- **Limitación conocida — varianza del juez:** entre runs idénticos un veredicto
  puede moverse (ej. `adam` 3/3 → 2/3). Mitigación futura: promediar N runs o
  fijar criterios más atómicos.
- **Preguntas trampa incluidas:** un RAG que no sabe decir "no sé" no está listo.
  Las 4 out-of-scope son tan importantes como las 11 respondibles.

## Paso 7c — Deploy (Streamlit Cloud)

La demo pública usa un corpus sintético de 12 notas de ML/AI (en `demo_vault/`)
que vive en el repo — sin datos privados. El índice vectorial se construye
automáticamente al arrancar la app por primera vez (~30 s, ~$0.002 en embeddings).

### Cómo hacer tu propio deploy

1. **Fork** este repo en GitHub.

2. **Crea una cuenta** en [share.streamlit.io](https://share.streamlit.io) (gratis).

3. **Nueva app** → conecta tu fork → Main file: `app.py`.

4. **Settings → Secrets** — pega tus claves:

```toml
OPENAI_API_KEY = "sk-..."
ANTHROPIC_API_KEY = "sk-ant-..."
```

5. **Deploy.** En el primer arranque verás el spinner de construcción del índice.
   Desde el segundo arranque el índice ya está en disco y la app arranca instantáneo.

### Para usar tu propio vault (privado)

Si quieres desplegar con tus propias notas en lugar del corpus sintético:

1. Corre el pipeline completo localmente:
   ```bash
   python chunk_vault.py /ruta/a/tu/vault
   python embed_chunks.py
   python build_index.py
   ```
2. Sube el directorio `chroma/` a un bucket (S3, GCS) y descargálo al arrancar,
   o usa una vector DB gestionada en la nube (Pinecone, Qdrant Cloud) en lugar de
   ChromaDB local. Ambas opciones requieren modificar `search.py`.

Alternativa más simple: añade autenticación con
[`streamlit-authenticator`](https://github.com/mkhorasani/Streamlit-Authenticator)
y despliega con el corpus real (ya que el acceso está protegido).

### Arquitectura de la demo

```
demo_vault/*.md          ← corpus público sintético (12 notas)
  ↓ demo_setup.py         chunk + embed (OpenAI) + load (ChromaDB)
chroma/                  ← índice vectorial persistente en disco
  ↓ search.py             retrieval top-k
  ↓ ask.py                Claude genera con citas
  ↓ app.py                Streamlit UI
```

Cuando el contenedor de Streamlit Cloud reinicia (tras inactividad), `chroma/`
se pierde y `demo_setup.py` reconstruye el índice automáticamente al siguiente
acceso. Costo: ~$0.002 por reconstrucción (1 llamada a OpenAI Embeddings).
