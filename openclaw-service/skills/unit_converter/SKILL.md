---
name: unit_converter
description: Convert between units of measurement — distance, weight, temperature, volume, speed, and more
---

Convert values between units of measurement. This skill works entirely offline — no API calls needed.

## Supported conversions

**Distance:** km ↔ miles, meters ↔ feet, cm ↔ inches
**Weight:** kg ↔ pounds, grams ↔ ounces
**Temperature:** Celsius ↔ Fahrenheit ↔ Kelvin
**Volume:** litres ↔ gallons (US/UK), ml ↔ fl oz
**Speed:** km/h ↔ mph, m/s ↔ km/h
**Data:** MB ↔ GB ↔ TB (base-2 and base-10)
**Area:** m² ↔ ft², hectares ↔ acres

## Response format

Give the converted value with appropriate precision (2 decimal places for most conversions,
integers for clean results like "exactly 100 km/h = 62.14 mph").

Example: "100 miles is 160.93 kilometres."
Example: "72°F is 22.2°C."

For temperature, always use the exact formula, not an approximation.
For all others, use the standard conversion factor.

## Edge cases

- If the user asks for a unit you don't recognise, say so and ask them to clarify.
- If the value is negative (valid for temperature), handle it correctly.
