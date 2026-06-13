"""
ComfyUI 服务模块
封装 ComfyUI API 调用
"""

import logging
import json
import uuid
import asyncio
from pathlib import Path
from typing import Optional

import httpx

from ..config import settings
from ..core.characters import get_active
from ..core.context import load_character_profile

logger = logging.getLogger(__name__)



class ComfyUIService:
    """ComfyUI 服务"""

    def __init__(self):
        self.base_url = settings.comfyui.base_url
        self._client: Optional[httpx.AsyncClient] = None
        # 跟踪正在进行的任务
        self._active_tasks: dict[str, dict] = {}

    async def _get_client(self) -> httpx.AsyncClient:
        """获取 HTTP 客户端"""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=120.0  # 图像生成可能需要较长时间
            )
        return self._client

    async def check_status(self) -> bool:
        """检查 ComfyUI 是否运行"""
        try:
            client = await self._get_client()
            response = await client.get("/system_stats")
            return response.status_code == 200
        except Exception as e:
            logger.error(f"检查 ComfyUI 状态失败: {e}")
            return False

    async def queue_prompt(self, workflow: dict, client_id: str = None) -> str:
        """
        提交生图任务

        Args:
            workflow: ComfyUI 工作流 JSON
            client_id: 客户端 ID（可选）

        Returns:
            prompt_id: 任务 ID
        """
        client = await self._get_client()

        if client_id is None:
            client_id = str(uuid.uuid4())

        payload = {
            "prompt": workflow,
            "client_id": client_id
        }

        try:
            response = await client.post("/prompt", json=payload)
            response.raise_for_status()

            data = response.json()
            prompt_id = data["prompt_id"]

            logger.info(f"ComfyUI 任务已提交: prompt_id={prompt_id}")
            return prompt_id

        except httpx.HTTPStatusError as e:
            logger.error(f"ComfyUI API 错误: {e.response.status_code} - {e.response.text}")
            raise
        except Exception as e:
            logger.error(f"ComfyUI 提交任务失败: {e}")
            raise

    async def get_history(self, prompt_id: str) -> Optional[dict]:
        """获取任务历史"""
        client = await self._get_client()

        try:
            response = await client.get(f"/history/{prompt_id}")
            response.raise_for_status()

            data = response.json()
            return data.get(prompt_id)

        except Exception as e:
            logger.error(f"获取 ComfyUI 历史失败: {e}")
            return None

    async def get_image(self, filename: str, subfolder: str = "", folder_type: str = "output") -> bytes:
        """
        获取生成的图片

        Args:
            filename: 文件名
            subfolder: 子文件夹
            folder_type: 文件夹类型 (output, temp)

        Returns:
            图片二进制数据
        """
        client = await self._get_client()

        params = {
            "filename": filename,
            "subfolder": subfolder,
            "type": folder_type
        }

        try:
            response = await client.get("/view", params=params)
            response.raise_for_status()

            return response.content

        except Exception as e:
            logger.error(f"获取 ComfyUI 图片失败: {e}")
            raise

    async def wait_for_completion(
        self,
        prompt_id: str,
        poll_interval: float = 1.5,
        max_wait: float = 180.0
    ) -> Optional[dict]:
        """
        轮询等待 ComfyUI 任务完成

        Args:
            prompt_id: 任务 ID
            poll_interval: 轮询间隔（秒）
            max_wait: 最大等待时间（秒）

        Returns:
            完成后的 history 数据，超时返回 None
        """
        elapsed = 0.0

        while elapsed < max_wait:
            await asyncio.sleep(poll_interval)
            elapsed += poll_interval

            history = await self.get_history(prompt_id)
            if history is not None:
                logger.info(f"ComfyUI 任务完成: prompt_id={prompt_id}, 耗时={elapsed:.1f}s")
                return history

            logger.debug(f"等待 ComfyUI 任务完成: prompt_id={prompt_id}, 已等待={elapsed:.1f}s")

        logger.warning(f"ComfyUI 任务超时: prompt_id={prompt_id}, max_wait={max_wait}s")
        return None

    async def generate_image(
        self,
        workflow: dict,
        save_to: Path = None,
        poll_interval: float = 1.5,
        max_wait: float = 180.0
    ) -> Optional[str]:
        """
        生成图片并保存（完整流程：提交 → 轮询 → 获取 → 保存）

        Args:
            workflow: ComfyUI 工作流
            save_to: 保存路径（可选）
            poll_interval: 轮询间隔（秒）
            max_wait: 最大等待时间（秒）

        Returns:
            生成的图片本地路径，失败返回 None
        """
        # 1. 提交任务
        prompt_id = await self.queue_prompt(workflow)

        # 2. 轮询等待完成
        history = await self.wait_for_completion(prompt_id, poll_interval, max_wait)
        if not history:
            logger.error(f"获取 ComfyUI 任务结果失败: {prompt_id}")
            return None

        # 3. 提取图片信息
        outputs = history.get("outputs", {})
        for node_id, node_output in outputs.items():
            images = node_output.get("images", [])
            if images:
                image_info = images[0]
                filename = image_info["filename"]
                subfolder = image_info.get("subfolder", "")

                # 获取图片数据
                image_data = await self.get_image(filename, subfolder)

                # 保存图片
                if save_to:
                    save_to.parent.mkdir(parents=True, exist_ok=True)
                    with open(save_to, "wb") as f:
                        f.write(image_data)
                    logger.info(f"图片已保存: {save_to}")
                    return str(save_to)
                else:
                    # 保存到默认位置
                    save_dir = settings.get_images_dir(get_active())
                    save_dir.mkdir(parents=True, exist_ok=True)
                    default_path = save_dir / filename
                    default_path.write_bytes(image_data)
                    logger.info(f"图片已保存: {default_path}")
                    return str(default_path)

        logger.error(f"未找到生成的图片: {prompt_id}")
        return None

    @staticmethod
    def _normalize_prompt(prompt: str) -> str:
        """
        标准化 prompt 标签：去重（兼容空格/下划线差异）
        """
        tags = [t.strip() for t in prompt.split(",") if t.strip()]

        seen = set()
        result = []
        for tag in tags:
            norm = tag.lower().replace(" ", "_")
            if norm not in seen:
                seen.add(norm)
                result.append(tag)

        return ", ".join(result)

    def build_workflow_from_template(
        self,
        prompt: str,
        negative_prompt: str = "",
        workflow_name: str = None,
        seed: int = -1,
        width: int = None,
        height: int = None
    ) -> dict:
        """
        从工作流 JSON 模板构建 ComfyUI prompt

        读取工作流文件，找到 CLIPTextEncode 节点替换 prompt，
        其他参数（sampler/scheduler/steps/cfg）由工作流文件本身的 widgets_values 控制。

        Args:
            prompt: 正向提示词
            negative_prompt: 负向提示词
            workflow_name: 工作流文件名
            seed: 随机种子（-1 为随机）
            width: 覆盖宽度（可选）
            height: 覆盖高度（可选）

        Returns:
            ComfyUI API 格式的 prompt dict
        """
        import random
        import json
        from pathlib import Path

        # 工作流目录
        workflow_dir = Path("D:/ComfyUI/ComfyUI/user/default/workflows")
        wf_name = workflow_name or "waiNSFWIllustrious_v140.json"
        wf_path = workflow_dir / wf_name

        if not wf_path.exists():
            raise FileNotFoundError(f"工作流文件不存在: {wf_path}")

        with open(wf_path, "r", encoding="utf-8") as f:
            workflow_data = json.load(f)

        # 自动拼接角色默认标签到 prompt 前面（固化角色特征，LLM 不需要自己编）
        char = get_active()
        try:
            profile = load_character_profile(char)
            char_tags = f"{profile.get('avatar_role', '')}, {profile.get('body_type', '')}, {profile.get('appearance', '')}"
            char_tags = char_tags.strip(", ")
            if char_tags:
                prompt = f"{char_tags}, {prompt}"
                prompt = self._normalize_prompt(prompt)
                logger.info(f"已拼接角色标签并去重: {char_tags[:80]}...")
            else:
                logger.warning(f"角色标签为空（profile 字段缺失），使用原始 prompt")
        except Exception as e:
            logger.warning(f"加载角色标签失败，使用原始 prompt: {e}")

        # 构建节点链接映射
        links_map = {}
        if "links" in workflow_data:
            for link in workflow_data["links"]:
                if len(link) >= 6:
                    link_id = link[0]
                    source_node_id = str(link[1])
                    source_output_idx = link[2]
                    links_map[link_id] = [source_node_id, source_output_idx]

        # 构建 prompt dict
        prompt_data = {}
        for node in workflow_data.get("nodes", []):
            node_id = str(node["id"])
            class_type = node["type"]

            node_data = {"inputs": {}, "class_type": class_type}

            widgets_values = list(node.get("widgets_values", []))

            # 构建 widget name → value 映射
            # 遍历 inputs 中 link=null 且有 widget 的条目，按顺序对应 widgets_values
            widget_map = {}
            widget_idx = 0
            if "inputs" in node:
                for inp in node["inputs"]:
                    if inp.get("link") is None and "widget" in inp:
                        if widget_idx < len(widgets_values):
                            widget_map[inp["widget"]["name"]] = widgets_values[widget_idx]
                        widget_idx += 1

            # 处理节点输入：link 型映射到源节点，widget 型从 widget_map 取值
            if "inputs" in node:
                for inp in node["inputs"]:
                    inp_name = inp["name"]
                    link_id = inp.get("link")

                    if link_id is not None and link_id in links_map:
                        # 连线输入 → 映射到源节点
                        node_data["inputs"][inp_name] = links_map[link_id]
                    elif "widget" in inp:
                        # Widget 输入 → 从 widget_map 取值
                        wname = inp["widget"]["name"]
                        if wname in widget_map:
                            node_data["inputs"][inp_name] = widget_map[wname]

            # 覆盖特定输入（用户可控的参数）
            if class_type == "KSampler":
                # 直接设置所有 KSampler 参数，不依赖 widgets_values 映射
                # （KSampler 的 widgets_values 含 UI 控件如 "randomize"，位置映射会错位）
                node_data["inputs"]["seed"] = seed if seed >= 0 else random.randint(0, 2**31 - 1)
                node_data["inputs"]["steps"] = settings.comfyui.steps
                node_data["inputs"]["cfg"] = settings.comfyui.cfg
                node_data["inputs"]["sampler_name"] = settings.comfyui.sampler
                node_data["inputs"]["scheduler"] = settings.comfyui.scheduler
                node_data["inputs"]["denoise"] = 1.0

            elif class_type == "EmptyLatentImage":
                if width is not None:
                    node_data["inputs"]["width"] = width
                if height is not None:
                    node_data["inputs"]["height"] = height

            elif class_type == "SaveImage":
                node_data["inputs"]["filename_prefix"] = char

            elif class_type == "CLIPTextEncode":
                title = node.get("title", "")
                if "负" in title or "neg" in title.lower():
                    node_data["inputs"]["text"] = negative_prompt or "bad quality,worst quality,worst detail,sketch,censor"
                else:
                    node_data["inputs"]["text"] = prompt

            prompt_data[node_id] = node_data

        return prompt_data

    def get_task_status(self, prompt_id: str) -> dict:
        """
        获取任务状态（用于 REST 接口查询）

        Args:
            prompt_id: 任务 ID

        Returns:
            状态信息字典
        """
        return {
            "task_id": prompt_id,
            "status": "unknown",
            "message": "状态需通过 ComfyUI 查询"
        }

    async def close(self):
        """关闭客户端"""
        if self._client and not self._client.is_closed:
            await self._client.aclose()


# 全局 ComfyUI 服务实例
comfyui_service = ComfyUIService()
