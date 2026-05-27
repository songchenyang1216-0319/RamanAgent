# 模型分类清单

本文档基于当前环境下 `backend/core/model_registry.py` 的实际扫描结果，用来统一说明“当前可用模型”及其支持分类。

## 口径说明

- `model_type` 是前端/接口里常看的粗粒度类型，只用于快速展示。
- `supported_categories` 才是正式分类数组，后端会把它一路传给前端。
- `category_source` 表示分类来源：
  - `explicit`：注册表显式标注
  - `heuristic`：根据模型名规则自动识别
  - `default`：默认按文本对话处理
- `category_status` 表示该分类是否已经确认：
  - `confirmed`：已确认
  - `default`：默认推断，建议后续补充显式标注
- `vision_understanding` 表示可直接做图片理解、截图分析、OCR 前置等。
- `image_edit` 表示图像编辑，不等同于视觉问答能力。

## 当前可用模型

### 商汤日日新 SenseNova

| 模型 | model_type | supported_categories | category_source | category_status | supports_vision |
| --- | --- | --- | --- | --- | --- |
| `sensenova-6.7-flash-lite` | `vision` | `文本对话 / 视觉理解` | `explicit` | `confirmed` | `True` |
| `deepseek-v4-flash` | `text` | `文本对话` | `default` | `default` | `False` |

### OpenAI

| 模型 | model_type | supported_categories | category_source | category_status | supports_vision |
| --- | --- | --- | --- | --- | --- |
| `gpt-5.5` | `text` | `文本对话` | `default` | `default` | `False` |
| `gpt-5.4` | `text` | `文本对话` | `default` | `default` | `False` |
| `gpt-5.4-mini` | `text` | `文本对话` | `default` | `default` | `False` |
| `gpt-5.4-nano` | `text` | `文本对话` | `default` | `default` | `False` |
| `gpt-4.1` | `text` | `文本对话` | `default` | `default` | `False` |
| `gpt-4.1-mini` | `text` | `文本对话` | `default` | `default` | `False` |

### 通义千问

| 模型 | model_type | supported_categories | category_source | category_status | supports_vision |
| --- | --- | --- | --- | --- | --- |
| `qwen-plus` | `text` | `文本对话` | `default` | `default` | `False` |
| `qwen-flash` | `text` | `文本对话` | `default` | `default` | `False` |
| `qwen-turbo` | `text` | `文本对话` | `default` | `default` | `False` |
| `qwen3-coder-plus` | `text` | `文本对话` | `default` | `default` | `False` |
| `qwen3.6-plus` | `vision` | `文本对话 / 视觉理解` | `explicit` | `confirmed` | `True` |
| `qwen-image-edit-plus` | `image_edit` | `图像编辑` | `explicit` | `confirmed` | `False` |

### 智谱 GLM

| 模型 | model_type | supported_categories | category_source | category_status | supports_vision |
| --- | --- | --- | --- | --- | --- |
| `glm-5` | `text` | `文本对话` | `default` | `default` | `False` |
| `glm-5-turbo` | `text` | `文本对话` | `default` | `default` | `False` |
| `glm-4.7` | `text` | `文本对话` | `default` | `default` | `False` |
| `glm-4.6` | `text` | `文本对话` | `default` | `default` | `False` |
| `glm-4.5` | `text` | `文本对话` | `default` | `default` | `False` |
| `glm-4-plus` | `text` | `文本对话` | `default` | `default` | `False` |
| `glm-4-air` | `text` | `文本对话` | `default` | `default` | `False` |
| `glm-4-flash` | `text` | `文本对话` | `default` | `default` | `False` |

### 硅基流动

| 模型 | model_type | supported_categories | category_source | category_status | supports_vision |
| --- | --- | --- | --- | --- | --- |
| `Qwen/Qwen3-32B` | `text` | `文本对话` | `explicit` | `confirmed` | `False` |
| `Qwen/Qwen3-14B` | `text` | `文本对话` | `explicit` | `confirmed` | `False` |
| `Qwen/Qwen2.5-72B-Instruct` | `text` | `文本对话` | `explicit` | `confirmed` | `False` |
| `deepseek-ai/DeepSeek-V3` | `text` | `文本对话` | `explicit` | `confirmed` | `False` |
| `deepseek-ai/DeepSeek-R1` | `text` | `文本对话` | `explicit` | `confirmed` | `False` |
| `THUDM/GLM-4-9B-0414` | `text` | `文本对话` | `explicit` | `confirmed` | `False` |

### Gemini

| 模型 | model_type | supported_categories | category_source | category_status | supports_vision |
| --- | --- | --- | --- | --- | --- |
| `gemini-2.5-flash` | `vision` | `文本对话 / 视觉理解` | `explicit` | `confirmed` | `True` |
| `gemini-2.5-pro` | `vision` | `文本对话 / 视觉理解` | `explicit` | `confirmed` | `True` |
| `gemini-2.0-flash` | `vision` | `文本对话 / 视觉理解` | `explicit` | `confirmed` | `True` |

### Ollama

| 模型 | model_type | supported_categories | category_source | category_status | supports_vision |
| --- | --- | --- | --- | --- | --- |
| `qwen2.5:7b` | `text` | `文本对话` | `default` | `default` | `False` |
| `qwen2.5:14b` | `text` | `文本对话` | `default` | `default` | `False` |
| `qwen2.5-coder:7b` | `text` | `文本对话` | `default` | `default` | `False` |
| `llama3.1:8b` | `text` | `文本对话` | `default` | `default` | `False` |
| `deepseek-r1:7b` | `text` | `文本对话` | `default` | `default` | `False` |

## 以后新增模型时的要求

新增模型时，请同时把下面这些字段补齐：

- `supported_categories`
- `supported_category_labels`
- `category_summary`
- `category_source`
- `category_status`
- `supports_vision`
- `model_type`

这样前端模型列表、当前模型展示、图片路由和后续的 Skill 调度都能直接读取到一致的分类结果。
