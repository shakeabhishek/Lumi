#!/usr/bin/env node
/**
 * OpenClaw viability test — Phase 1 gate criterion.
 *
 * Tests tool-calling reliability of qwen2.5:1.5b via Ollama's native API.
 * OpenClaw's gateway does not forward external tool definitions, so we test
 * the model directly — this is the layer that matters for Lumi's skill routing.
 *
 * Gate: ≥80% overall (40/50) to keep OpenClaw in V1.
 *
 * Prerequisites:
 *   ollama serve    (Ollama running with qwen2.5:1.5b pulled)
 *
 * Usage:
 *   npm run viability-test
 */

import { writeFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const LUMI_ROOT = join(__dirname, "..");

const OLLAMA_URL = "http://127.0.0.1:11434";
const MODEL = "qwen2.5:1.5b";
const MODEL_LABEL = "qwen2.5:1.5b (Ollama native API)";
const TIMEOUT_MS = 60_000;

// ── Tool definitions ──────────────────────────────────────────────────────────

const TOOLS = {
  weather: {
    type: "function",
    function: {
      name: "get_weather",
      description: "Get current weather conditions for a city or location",
      parameters: {
        type: "object",
        properties: {
          location: { type: "string", description: "City name, e.g. 'London' or 'Tokyo, JP'" },
        },
        required: ["location"],
      },
    },
  },
  timer: {
    type: "function",
    function: {
      name: "set_timer",
      description: "Set a countdown timer for a specified duration",
      parameters: {
        type: "object",
        properties: {
          duration_seconds: { type: "integer", description: "Duration in seconds" },
          label: { type: "string", description: "Optional label for the timer" },
        },
        required: ["duration_seconds"],
      },
    },
  },
  file_search: {
    type: "function",
    function: {
      name: "search_files",
      description: "Search for files and their contents in the Lumi sandbox directory",
      parameters: {
        type: "object",
        properties: {
          query: { type: "string", description: "Search term — matches filenames and content" },
        },
        required: ["query"],
      },
    },
  },
  unit_converter: {
    type: "function",
    function: {
      name: "convert_units",
      description: "Convert a value between units of measurement",
      parameters: {
        type: "object",
        properties: {
          value: { type: "number", description: "The numeric value to convert" },
          from_unit: { type: "string", description: "Source unit, e.g. 'miles', 'kg', 'fahrenheit'" },
          to_unit: { type: "string", description: "Target unit, e.g. 'km', 'pounds', 'celsius'" },
        },
        required: ["value", "from_unit", "to_unit"],
      },
    },
  },
  wikipedia_lookup: {
    type: "function",
    function: {
      name: "lookup_wikipedia",
      description: "Look up a topic on Wikipedia and return a summary",
      parameters: {
        type: "object",
        properties: {
          topic: { type: "string", description: "Topic to search for on Wikipedia" },
        },
        required: ["topic"],
      },
    },
  },
};

const ALL_TOOLS = Object.values(TOOLS);

// ── Test prompts ──────────────────────────────────────────────────────────────

const PROMPTS = {
  weather: [
    "What's the weather like in New York City?",
    "How hot is it in Tokyo right now?",
    "Is it raining in London today?",
    "What are the current conditions in Sydney?",
    "Tell me the weather in Paris.",
    "How's the weather in Mumbai?",
    "What's the temperature in Toronto?",
    "Check the weather in Berlin for me.",
    "Weather in Singapore please.",
    "What's it like outside in Dubai?",
  ],
  timer: [
    "Set a timer for 5 minutes.",
    "Remind me in 30 seconds.",
    "Can you set a 10-minute timer?",
    "Start a 2-minute countdown.",
    "Set a timer for 1 hour.",
    "I need a 45-second timer.",
    "Set a 3-minute timer for my tea.",
    "Give me a 15-minute work timer.",
    "Start a half-hour timer.",
    "Set a 90-second timer.",
  ],
  file_search: [
    "Find files about Python in my sandbox.",
    "Search for notes about Lumi.",
    "Look for any markdown files in my sandbox.",
    "Find anything related to machine learning.",
    "Search my files for 'project'.",
    "Are there any JSON files in the sandbox?",
    "Find files containing the word 'TODO'.",
    "Search for notes about design.",
    "Look for any files about hardware.",
    "Find documents mentioning Raspberry Pi.",
  ],
  unit_converter: [
    "Convert 100 miles to kilometres.",
    "How many pounds is 5 kilograms?",
    "What is 72 degrees Fahrenheit in Celsius?",
    "Convert 1 gallon to litres.",
    "How many feet is 2 metres?",
    "Convert 60 mph to km/h.",
    "What's 250 grams in ounces?",
    "How many centimetres is 6 feet?",
    "Convert 100 kilometres to miles.",
    "What is 0 degrees Celsius in Fahrenheit?",
  ],
  wikipedia_lookup: [
    "Look up Alan Turing on Wikipedia.",
    "Give me the Wikipedia article on quantum computing.",
    "What does Wikipedia say about the Raspberry Pi?",
    "Search Wikipedia for machine learning.",
    "Look up the history of the internet on Wikipedia.",
    "Get me the Wikipedia summary for the Turing test.",
    "Wikipedia article on the Python programming language please.",
    "Look up neural networks on Wikipedia.",
    "Find the Wikipedia page on Ada Lovelace.",
    "Wikipedia summary of artificial intelligence.",
  ],
};

// ── Test runner ───────────────────────────────────────────────────────────────

async function callOllama(prompt) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), TIMEOUT_MS);

  try {
    const response = await fetch(`${OLLAMA_URL}/api/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        model: MODEL,
        messages: [{ role: "user", content: prompt }],
        tools: ALL_TOOLS,
        stream: false,
      }),
      signal: controller.signal,
    });

    const data = await response.json();

    if (!response.ok) {
      throw new Error(`HTTP ${response.status}: ${JSON.stringify(data)}`);
    }

    // Ollama native API: data.message.tool_calls (not data.choices[...])
    const toolCalls = data.message?.tool_calls ?? [];
    const toolCalled = toolCalls[0]?.function?.name ?? null;
    return { toolCalled, raw: data };
  } finally {
    clearTimeout(timeout);
  }
}

async function runSkillTests(skillName, prompts, expectedTool) {
  const results = [];
  process.stdout.write(`  ${skillName.padEnd(20)}`);

  for (const prompt of prompts) {
    const start = Date.now();
    let result;

    try {
      const { toolCalled } = await callOllama(prompt);
      const success = toolCalled === expectedTool;
      result = { prompt, success, toolCalled, expected: expectedTool, latency: Date.now() - start };
    } catch (err) {
      result = {
        prompt,
        success: false,
        toolCalled: null,
        expected: expectedTool,
        latency: Date.now() - start,
        error: err.message,
      };
    }

    results.push(result);
    process.stdout.write(result.success ? "✓" : "✗");
  }

  const passed = results.filter((r) => r.success).length;
  const avgLatency = Math.round(results.reduce((s, r) => s + r.latency, 0) / results.length);
  process.stdout.write(`  ${passed}/${prompts.length}  avg ${avgLatency}ms\n`);
  return results;
}

function buildReport(allResults, startedAt) {
  const skills = Object.keys(allResults);
  const rows = skills.map((skill) => {
    const results = allResults[skill];
    const passed = results.filter((r) => r.success).length;
    const avgLatency = Math.round(results.reduce((s, r) => s + r.latency, 0) / results.length);
    return { skill, passed, total: results.length, avgLatency };
  });

  const totalPassed = rows.reduce((s, r) => s + r.passed, 0);
  const totalTests = rows.reduce((s, r) => s + r.total, 0);
  const overallPct = Math.round((totalPassed / totalTests) * 100);
  const gate = overallPct >= 80 ? "PASS ✓" : overallPct >= 60 ? "MARGINAL ⚠️" : "FAIL ✗";

  const failures = Object.entries(allResults)
    .flatMap(([skill, results]) =>
      results
        .filter((r) => !r.success)
        .map((r) => `- **${skill}**: "${r.prompt}" → called \`${r.toolCalled ?? "none"}\` (expected \`${r.expected}\`)${r.error ? ` — error: ${r.error}` : ""}`)
    )
    .join("\n");

  return `# OpenClaw Viability Report

Date: ${startedAt.toISOString().slice(0, 10)}
OpenClaw version: 2026.5.7
Model: ${MODEL_LABEL}
Test: ${totalTests} invocations, ${skills.length} skills, ${totalTests / skills.length} per skill

## Results

| Skill | Success | Avg latency |
|---|---|---|
${rows.map((r) => `| \`${r.skill}\` | ${r.passed}/${r.total} (${Math.round((r.passed / r.total) * 100)}%) | ${r.avgLatency}ms |`).join("\n")}
| **Overall** | **${totalPassed}/${totalTests} (${overallPct}%)** | |

## Gate criterion: ≥80% (${Math.ceil(totalTests * 0.8)}/${totalTests})

**Result: ${gate}**

${overallPct >= 80 ? "→ Continue with OpenClaw in V1." : overallPct >= 60 ? "→ Marginal result. Consider scoping down to skills with ≥80% individual reliability, or investigate fine-tuning options." : "→ Tool-calling unreliable with this model. Fall back to native Python skills only; defer OpenClaw to V2 with cloud LLM."}

## Failure analysis

${failures || "No failures — all tests passed."}

## Notes

- Tests call Ollama's native API directly (qwen2.5:1.5b).
  OpenClaw's gateway does not forward external tool definitions — it routes through its
  own skills system. The model layer is what we're testing here.
- Success = model called the expected tool (correct routing), regardless of API result.
- Prompts are varied natural-language phrasings to test routing robustness.

## Raw results

\`\`\`json
${JSON.stringify(allResults, null, 2)}
\`\`\`
`;
}

// ── Main ──────────────────────────────────────────────────────────────────────

async function main() {
  const startedAt = new Date();
  console.log("OpenClaw Viability Test");
  console.log(`Ollama: ${OLLAMA_URL}  Model: ${MODEL_LABEL}`);
  console.log(`Running 50 invocations (10 per skill)...\n`);
  console.log(`  ${"Skill".padEnd(20)}Results          Pass/Total  Latency`);
  console.log(`  ${"-".repeat(60)}`);

  // Verify Ollama is up and model is available
  try {
    const tags = await fetch(`${OLLAMA_URL}/api/tags`);
    if (!tags.ok) throw new Error(`status ${tags.status}`);
    const { models } = await tags.json();
    const has = models.some((m) => m.name === MODEL || m.name.startsWith(MODEL.split(":")[0]));
    if (!has) throw new Error(`model ${MODEL} not found — run: ollama pull ${MODEL}`);
  } catch (err) {
    console.error(`\nERROR: Cannot reach Ollama at ${OLLAMA_URL}`);
    console.error(`  → ${err.message}`);
    console.error(`  → Start Ollama first: ollama serve`);
    process.exit(1);
  }

  const allResults = {};
  for (const [skill, prompts] of Object.entries(PROMPTS)) {
    const expectedTool = TOOLS[skill].function.name;
    allResults[skill] = await runSkillTests(skill, prompts, expectedTool);
  }

  const totalPassed = Object.values(allResults)
    .flat()
    .filter((r) => r.success).length;
  const overallPct = Math.round((totalPassed / 50) * 100);

  console.log(`\n  ${"─".repeat(60)}`);
  console.log(`  Overall: ${totalPassed}/50 (${overallPct}%) — Gate: ${overallPct >= 80 ? "PASS ✓" : overallPct >= 60 ? "MARGINAL ⚠️" : "FAIL ✗"}`);

  const report = buildReport(allResults, startedAt);
  const reportPath = join(LUMI_ROOT, "docs", "openclaw-viability-report.md");
  writeFileSync(reportPath, report, "utf8");
  console.log(`\nReport written to: docs/openclaw-viability-report.md`);
}

main().catch((err) => {
  console.error("Unexpected error:", err);
  process.exit(1);
});
