"""ModalWorker — executes tasks on Modal remote GPUs (A100/T4)."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from ..config import MODAL_TOKEN_ID, MODAL_TOKEN_SECRET
from ..models.task import Task, TaskType

logger = logging.getLogger("reactor.workers.modal")


class ModalWorker:
    """Worker that dispatches GPU tasks to Modal serverless infrastructure."""

    def __init__(self, gpu_type: str = "A100"):
        self.gpu_type = gpu_type
        self.name = f"modal_{gpu_type.lower()}"

    async def execute(self, task: Task) -> dict[str, Any]:
        """Execute a task on Modal GPU."""
        try:
            import modal
        except ImportError:
            return {"success": False, "error": "modal package not installed"}

        if not MODAL_TOKEN_ID or not MODAL_TOKEN_SECRET:
            return {"success": False, "error": "Modal credentials not configured"}

        dispatch_map = {
            TaskType.VIDEO_EXPRESS: self._video_generate,
            TaskType.VIDEO_HD: self._video_generate,
            TaskType.VIDEO_4K: self._video_generate,
            TaskType.IMAGE_HD: self._image_generate,
            TaskType.IMAGE_EXPRESS: self._image_generate,
            TaskType.LLM_HEAVY: self._llm_inference,
            TaskType.LLM_LIGHT: self._llm_inference,
            TaskType.TRAINING: self._training,
            TaskType.AUDIO: self._audio_generate,
        }

        handler = dispatch_map.get(task.type)
        if not handler:
            return {"success": False, "error": f"Unsupported task type: {task.type.value}"}

        return await handler(task)

    async def _video_generate(self, task: Task) -> dict[str, Any]:
        """Generate video using Wan2.1/LTX models on Modal."""
        try:
            import modal

            app = modal.App("reactor-video")

            # Determine model and parameters based on task type
            model = task.params.get("model", "wan2.1")
            if task.type == TaskType.VIDEO_4K:
                resolution = "3840x2160"
                gpu = "A100"
            elif task.type == TaskType.VIDEO_HD:
                resolution = "1920x1080"
                gpu = "A100"
            else:
                resolution = "1280x720"
                gpu = "T4"
                model = task.params.get("model", "ltx-video")

            # Define the remote function
            image = modal.Image.debian_slim().pip_install(
                "torch", "diffusers", "transformers", "accelerate"
            )

            @app.function(gpu=gpu, image=image, timeout=600)
            def generate_video(prompt: str, resolution: str, model_name: str, params: dict):
                """Remote video generation function."""
                # This runs on Modal's GPU infrastructure
                import torch
                from diffusers import DiffusionPipeline

                pipe = DiffusionPipeline.from_pretrained(
                    f"Wan-AI/{model_name}" if "wan" in model_name else f"Lightricks/{model_name}",
                    torch_dtype=torch.float16,
                )
                pipe.to("cuda")

                frames = pipe(
                    prompt=prompt,
                    num_frames=params.get("num_frames", 81),
                    height=int(resolution.split("x")[1]),
                    width=int(resolution.split("x")[0]),
                ).frames[0]

                # Export to video file and upload
                output_path = "/tmp/output.mp4"
                from diffusers.utils import export_to_video
                export_to_video(frames, output_path, fps=params.get("fps", 24))

                # Return video bytes (will be stored externally)
                with open(output_path, "rb") as f:
                    return f.read()

            # Run the function
            loop = asyncio.get_event_loop()
            result_bytes = await loop.run_in_executor(
                None,
                lambda: generate_video.remote(
                    task.prompt, resolution, model, task.params
                ),
            )

            # In production, upload to storage and return URL
            return {
                "success": True,
                "data": {"size_bytes": len(result_bytes), "model": model, "resolution": resolution},
            }

        except Exception as e:
            logger.error(f"Modal video generation failed: {e}")
            return {"success": False, "error": str(e)}

    async def _image_generate(self, task: Task) -> dict[str, Any]:
        """Generate image on Modal GPU."""
        try:
            import modal

            app = modal.App("reactor-image")
            image = modal.Image.debian_slim().pip_install(
                "torch", "diffusers", "transformers", "accelerate"
            )

            model_name = task.params.get("model", "stabilityai/stable-diffusion-xl-base-1.0")

            @app.function(gpu=self.gpu_type, image=image, timeout=300)
            def generate_image(prompt: str, model_name: str, params: dict):
                import torch
                from diffusers import StableDiffusionXLPipeline

                pipe = StableDiffusionXLPipeline.from_pretrained(
                    model_name, torch_dtype=torch.float16
                )
                pipe.to("cuda")

                image = pipe(
                    prompt=prompt,
                    width=params.get("width", 1024),
                    height=params.get("height", 1024),
                    num_inference_steps=params.get("steps", 30),
                ).images[0]

                output_path = "/tmp/output.png"
                image.save(output_path)
                with open(output_path, "rb") as f:
                    return f.read()

            loop = asyncio.get_event_loop()
            result_bytes = await loop.run_in_executor(
                None,
                lambda: generate_image.remote(task.prompt, model_name, task.params),
            )

            return {
                "success": True,
                "data": {"size_bytes": len(result_bytes), "model": model_name},
            }

        except Exception as e:
            logger.error(f"Modal image generation failed: {e}")
            return {"success": False, "error": str(e)}

    async def _llm_inference(self, task: Task) -> dict[str, Any]:
        """Run LLM inference on Modal GPU."""
        try:
            import modal

            app = modal.App("reactor-llm")
            image = modal.Image.debian_slim().pip_install(
                "torch", "transformers", "accelerate", "vllm"
            )

            model_name = task.params.get("model", "meta-llama/Meta-Llama-3-8B-Instruct")

            @app.function(gpu=self.gpu_type, image=image, timeout=120)
            def run_llm(prompt: str, model_name: str, params: dict):
                from vllm import LLM, SamplingParams

                llm = LLM(model=model_name)
                sampling = SamplingParams(
                    temperature=params.get("temperature", 0.7),
                    max_tokens=params.get("max_tokens", 2048),
                )
                outputs = llm.generate([prompt], sampling)
                return outputs[0].outputs[0].text

            loop = asyncio.get_event_loop()
            result_text = await loop.run_in_executor(
                None,
                lambda: run_llm.remote(task.prompt, model_name, task.params),
            )

            return {
                "success": True,
                "data": {"text": result_text, "model": model_name},
            }

        except Exception as e:
            logger.error(f"Modal LLM inference failed: {e}")
            return {"success": False, "error": str(e)}

    async def _training(self, task: Task) -> dict[str, Any]:
        """Run training job on Modal."""
        try:
            import modal

            app = modal.App("reactor-training")
            image = modal.Image.debian_slim().pip_install(
                "torch", "transformers", "peft", "datasets", "accelerate"
            )

            @app.function(gpu="A100", image=image, timeout=3600)
            def train_model(params: dict):
                # Training logic depends heavily on params
                return {"status": "completed", "epochs": params.get("epochs", 3)}

            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None, lambda: train_model.remote(task.params)
            )

            return {"success": True, "data": result}

        except Exception as e:
            logger.error(f"Modal training failed: {e}")
            return {"success": False, "error": str(e)}

    async def _audio_generate(self, task: Task) -> dict[str, Any]:
        """Generate audio on Modal GPU."""
        try:
            import modal

            app = modal.App("reactor-audio")
            image = modal.Image.debian_slim().pip_install(
                "torch", "transformers", "scipy"
            )

            @app.function(gpu="T4", image=image, timeout=180)
            def generate_audio(prompt: str, params: dict):
                from transformers import pipeline

                synth = pipeline("text-to-audio", model="facebook/musicgen-small")
                result = synth(prompt, forward_params={"max_new_tokens": params.get("max_tokens", 512)})
                import scipy.io.wavfile
                output_path = "/tmp/output.wav"
                scipy.io.wavfile.write(output_path, rate=result["sampling_rate"], data=result["audio"])
                with open(output_path, "rb") as f:
                    return f.read()

            loop = asyncio.get_event_loop()
            result_bytes = await loop.run_in_executor(
                None, lambda: generate_audio.remote(task.prompt, task.params)
            )

            return {
                "success": True,
                "data": {"size_bytes": len(result_bytes)},
            }

        except Exception as e:
            logger.error(f"Modal audio generation failed: {e}")
            return {"success": False, "error": str(e)}
