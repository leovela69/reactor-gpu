# ⚡ REACTOR — Central Electrica C8L

Bot independiente que gestiona GPUs gratuitas y distribuye tareas de IA entre multiples fuentes de computacion.

## Arquitectura

```
Leon/Sayan/Hermes -> POST /api/generate -> REACTOR decide -> Worker ejecuta -> Resultado
```

### Capas:
1. **Cerebro (Oracle ARM 24GB)** — Coordinador 24/7, LLM local, cache
2. **Musculo (GPUs bajo demanda)** — Modal, Kaggle, Lightning, Colab
3. **Energia Rapida (APIs)** — Magic Hour, Kling, Veo 3, Agnes, Seedance, HuggingFace

## Capacidades

| Tarea | GPU Necesaria | Worker |
|-------|--------------|--------|
| Video HD (Wan 14B) | 32-40GB VRAM | Modal A100 |
| Video rapido (LTX-2) | 16GB VRAM | Kaggle T4 |
| Imagenes 4K (Flux/SD3) | 16-24GB VRAM | Kaggle/Lightning |
| LLM pesado (Llama 70B) | 40GB VRAM | Modal A100 (Q4) |
| Training LoRA | 24GB VRAM | Lightning A10G |
| Video Express | 0 (API) | Magic Hour/Kling/Agnes |
| Musica IA | 8-16GB | Kaggle T4 |

## Pool de Recursos Gratis

| Fuente | Recurso | Cuota |
|--------|---------|-------|
| Oracle Cloud | 24GB RAM ARM (siempre) | infinito |
| Modal | T4-A100 serverless | $30/mes |
| Kaggle | T4 16GB | 30h/semana |
| Google Colab | T4 16GB | 30h/semana |
| Lightning.ai | A10G 24GB | 22h/mes |
| Magic Hour | Videos HD | 100/dia |
| Kling AI | Videos cinematicos | 66/dia |
| Google Veo 3 | Videos 4K | 100/mes |
| Agnes AI | Videos ilimitados | infinito (lento) |
| HuggingFace | Inference API | infinito (rate limited) |

**Total: ~850+ generaciones/mes, 120h GPU/mes, $0**

## Deploy

```bash
# Oracle ARM (primario)
docker-compose up -d

# VPS Hostinger (backup)
python -m reactor.main
```

## API

```bash
# Generar video
curl -X POST http://reactor:9091/api/generate \
  -H "Authorization: Bearer $BRIDGE_SECRET" \
  -d '{"type": "video_express", "prompt": "golden lion neon city", "priority": "normal"}'

# Ver cuotas
curl http://reactor:9091/api/quota -H "Authorization: Bearer $BRIDGE_SECRET"

# Estado
curl http://reactor:9091/api/status -H "Authorization: Bearer $BRIDGE_SECRET"
```

## Costo Total: $0/mes
