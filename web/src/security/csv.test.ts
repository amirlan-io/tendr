import { describe, expect, it } from "vitest";
import { escapeCsvCell } from "./csv";

describe("escapeCsvCell", () => {
  it("экранирует формулы с =", () => {
    expect(escapeCsvCell("=2+2")).toBe("\"'=2+2\"");
  });

  it("экранирует + - @", () => {
    expect(escapeCsvCell("+123")).toBe("\"'+123\"");
    expect(escapeCsvCell("-5")).toBe("\"'-5\"");
    expect(escapeCsvCell("@user")).toBe("\"'@user\"");
  });

  it("экранирует формулу после ведущих пробелов", () => {
    expect(escapeCsvCell("  =cmd")).toBe("\"'  =cmd\"");
  });

  it("не трогает обычный текст, но квотирует", () => {
    expect(escapeCsvCell("мебель")).toBe("\"мебель\"");
    expect(escapeCsvCell("")).toBe("\"\"");
  });

  it("удваивает кавычки", () => {
    expect(escapeCsvCell('ООО "Рога"')).toBe("\"ООО \"\"Рога\"\"\"");
  });

  it("обрабатывает null/undefined и числа", () => {
    expect(escapeCsvCell(null)).toBe("\"\"");
    expect(escapeCsvCell(123)).toBe("\"123\"");
  });
});
