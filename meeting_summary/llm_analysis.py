from openai import AzureOpenAI
from dotenv import load_dotenv
import base64
import os

load_dotenv()
GPT4o_API_KEY = os.getenv("GPT4o_API_KEY")
GPT4o_DEPLOYMENT_ENDPOINT = os.getenv("GPT4o_DEPLOYMENT_ENDPOINT")
GPT4o_DEPLOYMENT_NAME = os.getenv("GPT4o_DEPLOYMENT_NAME")


client = AzureOpenAI(
  azure_endpoint = GPT4o_DEPLOYMENT_ENDPOINT, 
  api_key=GPT4o_API_KEY,  
  api_version="2024-02-01"
)


def call_openAI(text):
    print(f"deploy is {GPT4o_DEPLOYMENT_ENDPOINT}")
    response = client.chat.completions.create(
        model=GPT4o_DEPLOYMENT_NAME,
        messages = text,
        temperature=0.0
    )
    return response.choices[0].message.content

def encode_image(image):
    
    return base64.b64encode(image).decode("utf-8")
    
def analysis_image(image, user_prompt: str | None = None, detected_language="en-US"):
    encoded_image = encode_image(image.getvalue())
    default_prompt = "Provide a clear, structured analysis of the image: key objects, relationships, actions, context, and any notable details relevant for documentation or presentation."
    question = user_prompt.strip() if user_prompt and user_prompt.strip() else default_prompt
    messages=[
        {"role": "system", "content": "You are a helpful assistant that analyzes images and visual content. Respond succinctly and clearly in English unless otherwise instructed."},
        {"role": "user", "content": [
            {"type": "text", "text": question},
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{encoded_image}"}}
        ]}
    ]
    result = call_openAI(messages)
    
    print(f"Image analysis result: {result}")
    return result

def analysis_text(userPrompt, text, detected_language="en-US"):
    # Define language-specific prompts
    language_prompts = {
        "en-US": "Please provide a comprehensive content summary focusing on key information and important points. Use clear English formatting.",
        "zh-CN": "请提供一份侧重于关键内容和重要信息的总结。使用良好的中文格式输出",
        "es-ES": "Por favor, proporciona un resumen completo del contenido enfocándose en la información clave y puntos importantes. Usa un formato claro en español.",
        "fr-FR": "Veuillez fournir un résumé complet du contenu en vous concentrant sur les informations clés et les points importants. Utilisez un format français clair.",
        "de-DE": "Bitte erstellen Sie eine umfassende Inhaltszusammenfassung mit Fokus auf wichtige Informationen und Kernpunkte. Verwenden Sie eine klare deutsche Formatierung.",
        "ja-JP": "重要な内容と要点に焦点を当てた包括的なコンテンツ要約を提供してください。明確な日本語の形式を使用してください。",
        "ko-KR": "주요 내용과 중요한 포인트에 중점을 둔 포괄적인 콘텐츠 요약을 제공해 주세요. 명확한 한국어 형식을 사용하세요."
    }
    
    # Get the appropriate prompt based on detected language, default to English
    base_prompt = language_prompts.get(detected_language, language_prompts["en-US"])
    
    # If user provided a custom prompt, use it; otherwise use the language-specific default
    final_prompt = userPrompt if userPrompt and userPrompt.strip() else base_prompt
    
    messages=[
        {"role": "system", "content": "You are a helpful assistant that responds in the same language as the input text. Help me with content analysis and summarization!"},
        {"role": "user", "content": [
            {"type": "text", "text": final_prompt},
            {"type": "text", "text": text}
        ]}
    ]
    result = call_openAI(messages)
    
    print(f"Text analysis result: {result}")
    return result