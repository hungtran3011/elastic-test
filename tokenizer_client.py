#!/usr/bin/env python
"""
Client for Cốc Cốc Tokenizer microservice.

The tokenizer splits Vietnamese text into words, properly handling compound words like:
  "học sinh" -> "học_sinh"
  "thành phố" -> "thành_phố"
  "điện thoại" -> "điện_thoại"

This ensures better search quality by treating compound words as single tokens.
"""

import requests
from typing import Optional
from settings import TOKENIZER_URL

def tokenize(text: str, use_coccoc: bool = True) -> str:
    """
    Tokenize Vietnamese text using Cốc Cốc tokenizer.
    
    Args:
        text: Vietnamese text to tokenize
        use_coccoc: If True, use Cốc Cốc tokenizer; if False, return original text
        
    Returns:
        Tokenized text with compound words joined by underscores
        
    Example:
        >>> tokenize("Tôi đang học tại thành phố Hà Nội")
        "Tôi đang học tại thành_phố Hà_Nội"
    """
    if not use_coccoc or not text:
        return text
    
    try:
        # Use GET request with query parameter (not POST with form data)
        response = requests.get(
            f"{TOKENIZER_URL}/tokenize",
            params={'text': text},
            timeout=5
        )
        response.raise_for_status()
        result = response.json()
        
        # The tokenizer returns an array of tokens: ["cốc_cốc", "là", "công_cụ", ...]
        # Join them back with spaces
        if isinstance(result, list):
            tokenized = " ".join(result)
        else:
            # Fallback if response format is different
            tokenized = result.get('result', text) if isinstance(result, dict) else text
            
        return tokenized
        
    except requests.exceptions.ConnectionError:
        print(f"⚠️  Warning: Tokenizer service at {TOKENIZER_URL} is not available")
        print("   Falling back to original text. Make sure Docker services are running.")
        return text
    except Exception as e:
        print(f"⚠️  Warning: Tokenizer error: {e}")
        return text


def batch_tokenize(texts: list, use_coccoc: bool = True) -> list:
    """
    Tokenize multiple texts efficiently.
    
    Args:
        texts: List of Vietnamese texts
        use_coccoc: If True, use Cốc Cốc tokenizer
        
    Returns:
        List of tokenized texts
    """
    return [tokenize(text, use_coccoc) for text in texts]


if __name__ == "__main__":
    # Test the tokenizer
    test_texts = [
        "Học sinh chuyên ngành điện tử",
        "Tôi sống tại thành phố Hà Nội",
        "Điện thoại thông minh rất tiện lợi",
        "Cốc Cốc là công cụ tìm kiếm Việt Nam"
    ]
    
    print("Testing Cốc Cốc Tokenizer:")
    print(f"Tokenizer URL: {TOKENIZER_URL}\n")
    
    for text in test_texts:
        tokenized = tokenize(text)
        print(f"Original:  {text}")
        print(f"Tokenized: {tokenized}")
        print()
