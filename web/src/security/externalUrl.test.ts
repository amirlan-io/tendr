import { describe, expect, it } from "vitest";
import {
  getSafeExternalUrl,
  getSafeHttpsUrl,
  isSafeExternalUrl,
  isSafeHttpsUrl,
} from "./externalUrl";

describe("getSafeExternalUrl", () => {
  it("разрешает goszakup.gov.kz по https", () => {
    expect(isSafeExternalUrl("https://goszakup.gov.kz/ru/announce/show/123")).toBe(true);
    expect(getSafeExternalUrl("https://goszakup.gov.kz/ru/announce/show/123")).toContain(
      "https://goszakup.gov.kz/",
    );
  });

  it("разрешает zakup.gov.kz по https", () => {
    expect(isSafeExternalUrl("https://zakup.gov.kz/lot/1")).toBe(true);
  });

  it("отклоняет javascript: URL", () => {
    expect(isSafeExternalUrl("javascript:alert(1)")).toBe(false);
    expect(getSafeExternalUrl("javascript:alert(1)")).toBeNull();
  });

  it("отклоняет data: URL", () => {
    expect(isSafeExternalUrl("data:text/html,<h1>x</h1>")).toBe(false);
    expect(getSafeExternalUrl("data:text/html,hi")).toBeNull();
  });

  it("отклоняет file: URL", () => {
    expect(isSafeExternalUrl("file:///etc/passwd")).toBe(false);
  });

  it("отклоняет http (только https)", () => {
    expect(isSafeExternalUrl("http://goszakup.gov.kz/lot/1")).toBe(false);
  });

  it("отклоняет evil-goszakup.gov.kz (без includes-трюков)", () => {
    expect(isSafeExternalUrl("https://evil-goszakup.gov.kz/lot/1")).toBe(false);
    expect(isSafeExternalUrl("https://goszakup.gov.kz.evil.com/lot")).toBe(false);
    expect(isSafeExternalUrl("https://notzakup.gov.kz/")).toBe(false);
  });

  it("отклоняет userinfo", () => {
    expect(isSafeExternalUrl("https://user:pass@goszakup.gov.kz/")).toBe(false);
    expect(isSafeExternalUrl("https://user@goszakup.gov.kz/")).toBe(false);
  });

  it("отклоняет нестандартный порт", () => {
    expect(isSafeExternalUrl("https://goszakup.gov.kz:8443/lot")).toBe(false);
  });

  it("отклоняет относительные и пустые URL", () => {
    expect(isSafeExternalUrl("/lots/1")).toBe(false);
    expect(isSafeExternalUrl("")).toBe(false);
    expect(isSafeExternalUrl(null)).toBe(false);
  });
});

describe("getSafeHttpsUrl (общая проверка для магазинов и агента)", () => {
  it("разрешает произвольный https-домен магазина", () => {
    expect(isSafeHttpsUrl("https://kaspi.kz/shop/p/noutbuk/")).toBe(true);
  });

  it("отклоняет javascript:/data:/http:/userinfo", () => {
    expect(isSafeHttpsUrl("javascript:alert(1)")).toBe(false);
    expect(isSafeHttpsUrl("data:text/html,hi")).toBe(false);
    expect(isSafeHttpsUrl("http://kaspi.kz/")).toBe(false);
    expect(isSafeHttpsUrl("https://user@kaspi.kz/")).toBe(false);
    expect(getSafeHttpsUrl("file:///etc/passwd")).toBeNull();
  });
});
