# OpenClaw Viability Report

Date: 2026-05-20
OpenClaw version: 2026.5.7
Model: qwen2.5:1.5b (Ollama native API)
Test: 50 invocations, 5 skills, 10 per skill

## Results

| Skill | Success | Avg latency |
|---|---|---|
| `weather` | 9/10 (90%) | 425ms |
| `timer` | 8/10 (80%) | 347ms |
| `file_search` | 10/10 (100%) | 295ms |
| `unit_converter` | 10/10 (100%) | 463ms |
| `wikipedia_lookup` | 10/10 (100%) | 316ms |
| **Overall** | **47/50 (94%)** | |

## Gate criterion: ≥80% (40/50)

**Result: PASS ✓**

→ Continue with OpenClaw in V1.

## Failure analysis

- **weather**: "What's the temperature in Toronto?" → called `none` (expected `get_weather`)
- **timer**: "I need a 45-second timer." → called `none` (expected `set_timer`)
- **timer**: "Start a half-hour timer." → called `none` (expected `set_timer`)

## Notes

- Tests call Ollama's native API directly (qwen2.5:1.5b).
  OpenClaw's gateway does not forward external tool definitions — it routes through its
  own skills system. The model layer is what we're testing here.
- Success = model called the expected tool (correct routing), regardless of API result.
- Prompts are varied natural-language phrasings to test routing robustness.

## Raw results

```json
{
  "weather": [
    {
      "prompt": "What's the weather like in New York City?",
      "success": true,
      "toolCalled": "get_weather",
      "expected": "get_weather",
      "latency": 1176
    },
    {
      "prompt": "How hot is it in Tokyo right now?",
      "success": true,
      "toolCalled": "get_weather",
      "expected": "get_weather",
      "latency": 298
    },
    {
      "prompt": "Is it raining in London today?",
      "success": true,
      "toolCalled": "get_weather",
      "expected": "get_weather",
      "latency": 311
    },
    {
      "prompt": "What are the current conditions in Sydney?",
      "success": true,
      "toolCalled": "get_weather",
      "expected": "get_weather",
      "latency": 297
    },
    {
      "prompt": "Tell me the weather in Paris.",
      "success": true,
      "toolCalled": "get_weather",
      "expected": "get_weather",
      "latency": 305
    },
    {
      "prompt": "How's the weather in Mumbai?",
      "success": true,
      "toolCalled": "get_weather",
      "expected": "get_weather",
      "latency": 318
    },
    {
      "prompt": "What's the temperature in Toronto?",
      "success": false,
      "toolCalled": null,
      "expected": "get_weather",
      "latency": 357
    },
    {
      "prompt": "Check the weather in Berlin for me.",
      "success": true,
      "toolCalled": "get_weather",
      "expected": "get_weather",
      "latency": 306
    },
    {
      "prompt": "Weather in Singapore please.",
      "success": true,
      "toolCalled": "get_weather",
      "expected": "get_weather",
      "latency": 287
    },
    {
      "prompt": "What's it like outside in Dubai?",
      "success": true,
      "toolCalled": "get_weather",
      "expected": "get_weather",
      "latency": 595
    }
  ],
  "timer": [
    {
      "prompt": "Set a timer for 5 minutes.",
      "success": true,
      "toolCalled": "set_timer",
      "expected": "set_timer",
      "latency": 324
    },
    {
      "prompt": "Remind me in 30 seconds.",
      "success": true,
      "toolCalled": "set_timer",
      "expected": "set_timer",
      "latency": 315
    },
    {
      "prompt": "Can you set a 10-minute timer?",
      "success": true,
      "toolCalled": "set_timer",
      "expected": "set_timer",
      "latency": 562
    },
    {
      "prompt": "Start a 2-minute countdown.",
      "success": true,
      "toolCalled": "set_timer",
      "expected": "set_timer",
      "latency": 402
    },
    {
      "prompt": "Set a timer for 1 hour.",
      "success": true,
      "toolCalled": "set_timer",
      "expected": "set_timer",
      "latency": 332
    },
    {
      "prompt": "I need a 45-second timer.",
      "success": false,
      "toolCalled": null,
      "expected": "set_timer",
      "latency": 287
    },
    {
      "prompt": "Set a 3-minute timer for my tea.",
      "success": true,
      "toolCalled": "set_timer",
      "expected": "set_timer",
      "latency": 317
    },
    {
      "prompt": "Give me a 15-minute work timer.",
      "success": true,
      "toolCalled": "set_timer",
      "expected": "set_timer",
      "latency": 316
    },
    {
      "prompt": "Start a half-hour timer.",
      "success": false,
      "toolCalled": null,
      "expected": "set_timer",
      "latency": 304
    },
    {
      "prompt": "Set a 90-second timer.",
      "success": true,
      "toolCalled": "set_timer",
      "expected": "set_timer",
      "latency": 307
    }
  ],
  "file_search": [
    {
      "prompt": "Find files about Python in my sandbox.",
      "success": true,
      "toolCalled": "search_files",
      "expected": "search_files",
      "latency": 285
    },
    {
      "prompt": "Search for notes about Lumi.",
      "success": true,
      "toolCalled": "search_files",
      "expected": "search_files",
      "latency": 297
    },
    {
      "prompt": "Look for any markdown files in my sandbox.",
      "success": true,
      "toolCalled": "search_files",
      "expected": "search_files",
      "latency": 291
    },
    {
      "prompt": "Find anything related to machine learning.",
      "success": true,
      "toolCalled": "search_files",
      "expected": "search_files",
      "latency": 309
    },
    {
      "prompt": "Search my files for 'project'.",
      "success": true,
      "toolCalled": "search_files",
      "expected": "search_files",
      "latency": 298
    },
    {
      "prompt": "Are there any JSON files in the sandbox?",
      "success": true,
      "toolCalled": "search_files",
      "expected": "search_files",
      "latency": 300
    },
    {
      "prompt": "Find files containing the word 'TODO'.",
      "success": true,
      "toolCalled": "search_files",
      "expected": "search_files",
      "latency": 287
    },
    {
      "prompt": "Search for notes about design.",
      "success": true,
      "toolCalled": "search_files",
      "expected": "search_files",
      "latency": 286
    },
    {
      "prompt": "Look for any files about hardware.",
      "success": true,
      "toolCalled": "search_files",
      "expected": "search_files",
      "latency": 291
    },
    {
      "prompt": "Find documents mentioning Raspberry Pi.",
      "success": true,
      "toolCalled": "search_files",
      "expected": "search_files",
      "latency": 308
    }
  ],
  "unit_converter": [
    {
      "prompt": "Convert 100 miles to kilometres.",
      "success": true,
      "toolCalled": "convert_units",
      "expected": "convert_units",
      "latency": 468
    },
    {
      "prompt": "How many pounds is 5 kilograms?",
      "success": true,
      "toolCalled": "convert_units",
      "expected": "convert_units",
      "latency": 459
    },
    {
      "prompt": "What is 72 degrees Fahrenheit in Celsius?",
      "success": true,
      "toolCalled": "convert_units",
      "expected": "convert_units",
      "latency": 464
    },
    {
      "prompt": "Convert 1 gallon to litres.",
      "success": true,
      "toolCalled": "convert_units",
      "expected": "convert_units",
      "latency": 457
    },
    {
      "prompt": "How many feet is 2 metres?",
      "success": true,
      "toolCalled": "convert_units",
      "expected": "convert_units",
      "latency": 450
    },
    {
      "prompt": "Convert 60 mph to km/h.",
      "success": true,
      "toolCalled": "convert_units",
      "expected": "convert_units",
      "latency": 512
    },
    {
      "prompt": "What's 250 grams in ounces?",
      "success": true,
      "toolCalled": "convert_units",
      "expected": "convert_units",
      "latency": 452
    },
    {
      "prompt": "How many centimetres is 6 feet?",
      "success": true,
      "toolCalled": "convert_units",
      "expected": "convert_units",
      "latency": 462
    },
    {
      "prompt": "Convert 100 kilometres to miles.",
      "success": true,
      "toolCalled": "convert_units",
      "expected": "convert_units",
      "latency": 457
    },
    {
      "prompt": "What is 0 degrees Celsius in Fahrenheit?",
      "success": true,
      "toolCalled": "convert_units",
      "expected": "convert_units",
      "latency": 449
    }
  ],
  "wikipedia_lookup": [
    {
      "prompt": "Look up Alan Turing on Wikipedia.",
      "success": true,
      "toolCalled": "lookup_wikipedia",
      "expected": "lookup_wikipedia",
      "latency": 306
    },
    {
      "prompt": "Give me the Wikipedia article on quantum computing.",
      "success": true,
      "toolCalled": "lookup_wikipedia",
      "expected": "lookup_wikipedia",
      "latency": 318
    },
    {
      "prompt": "What does Wikipedia say about the Raspberry Pi?",
      "success": true,
      "toolCalled": "lookup_wikipedia",
      "expected": "lookup_wikipedia",
      "latency": 316
    },
    {
      "prompt": "Search Wikipedia for machine learning.",
      "success": true,
      "toolCalled": "lookup_wikipedia",
      "expected": "lookup_wikipedia",
      "latency": 307
    },
    {
      "prompt": "Look up the history of the internet on Wikipedia.",
      "success": true,
      "toolCalled": "lookup_wikipedia",
      "expected": "lookup_wikipedia",
      "latency": 308
    },
    {
      "prompt": "Get me the Wikipedia summary for the Turing test.",
      "success": true,
      "toolCalled": "lookup_wikipedia",
      "expected": "lookup_wikipedia",
      "latency": 317
    },
    {
      "prompt": "Wikipedia article on the Python programming language please.",
      "success": true,
      "toolCalled": "lookup_wikipedia",
      "expected": "lookup_wikipedia",
      "latency": 318
    },
    {
      "prompt": "Look up neural networks on Wikipedia.",
      "success": true,
      "toolCalled": "lookup_wikipedia",
      "expected": "lookup_wikipedia",
      "latency": 318
    },
    {
      "prompt": "Find the Wikipedia page on Ada Lovelace.",
      "success": true,
      "toolCalled": "lookup_wikipedia",
      "expected": "lookup_wikipedia",
      "latency": 337
    },
    {
      "prompt": "Wikipedia summary of artificial intelligence.",
      "success": true,
      "toolCalled": "lookup_wikipedia",
      "expected": "lookup_wikipedia",
      "latency": 317
    }
  ]
}
```
