import { describe, expect, it } from "vitest";
import {
  buildGoszakupUrl,
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

  it("разрешает v3bl.goszakup.gov.kz — парсер отдаёт ссылки на этот поддомен", () => {
    expect(
      isSafeExternalUrl("https://v3bl.goszakup.gov.kz/ru/announce/index/17726443-1"),
    ).toBe(true);
    expect(
      getSafeExternalUrl("https://v3bl.goszakup.gov.kz/ru/announce/index/17726443-1"),
    ).toBe("https://v3bl.goszakup.gov.kz/ru/announce/index/17726443-1");
  });

  it("разрешает www-поддомены goszakup/zakup", () => {
    expect(isSafeExternalUrl("https://www.goszakup.gov.kz/ru")).toBe(true);
    expect(isSafeExternalUrl("https://www.zakup.gov.kz/ru")).toBe(true);
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
    // Поддомен должен быть ровно из allowlist, любой другой — нет.
    expect(isSafeExternalUrl("https://v3bl.goszakup.gov.kz.evil.com/ru")).toBe(false);
    expect(isSafeExternalUrl("https://evilv3bl.goszakup.gov.kz/ru")).toBe(false);
    expect(isSafeExternalUrl("https://gov.kz.evil.com/ru")).toBe(false);
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

describe("buildGoszakupUrl", () => {
  it("строит ссылку на объявление по числовому ID", () => {
    expect(buildGoszakupUrl("17726443")).toBe(
      "https://goszakup.gov.kz/ru/announce/index/17726443",
    );
  });

  it("сохраняет суффикс лота", () => {
    expect(buildGoszakupUrl("17726443-1")).toBe(
      "https://goszakup.gov.kz/ru/announce/index/17726443-1",
    );
  });

  it("отклоняет не-числовой и слишком короткий ввод", () => {
    expect(buildGoszakupUrl("abc")).toBeNull();
    expect(buildGoszakupUrl("12345")).toBeNull();
    expect(buildGoszakupUrl("17726443-1-extra")).toBeNull();
    expect(buildGoszakupUrl("")).toBeNull();
    expect(buildGoszakupUrl(null)).toBeNull();
  });

  it("не позволяет подмешать свою схему или хост", () => {
    expect(buildGoszakupUrl("https://evil.com/17726443")).toBeNull();
    expect(buildGoszakupUrl("17726443/../admin")).toBeNull();
  });

  it("результат проходит строгую проверку allowlist", () => {
    expect(isSafeExternalUrl(buildGoszakupUrl("17726443"))).toBe(true);
  });
});
