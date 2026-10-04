import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { LotSourceLink, LotSourceIconButton, resolveLotSourceUrl } from "./LotSourceLink";

afterEach(() => {
  cleanup();
});

describe("resolveLotSourceUrl", () => {
  it("предпочитает готовый source_url с площадки", () => {
    expect(
      resolveLotSourceUrl("https://v3bl.goszakup.gov.kz/ru/announce/index/17726443-1", "17726443"),
    ).toBe("https://v3bl.goszakup.gov.kz/ru/announce/index/17726443-1");
  });

  it("строит ссылку из ID, когда source_url пуст", () => {
    expect(resolveLotSourceUrl(null, "17726443")).toBe(
      "https://goszakup.gov.kz/ru/announce/index/17726443",
    );
    expect(resolveLotSourceUrl(undefined, "17726443")).toContain("17726443");
  });

  it("игнорирует непригодный source_url (upload:, http:, чужой хост)", () => {
    // Загруженный файл — не объявление, но у него есть числовой ID.
    expect(resolveLotSourceUrl("upload:tz.docx", "17726443")).toBe(
      "https://goszakup.gov.kz/ru/announce/index/17726443",
    );
    expect(resolveLotSourceUrl("http://goszakup.gov.kz/ru", "17726443")).toContain("17726443");
    expect(resolveLotSourceUrl("https://evil.com/x", "17726443")).toContain("17726443");
  });

  it("возвращает null, когда нет ни валидной ссылки, ни числового ID", () => {
    expect(resolveLotSourceUrl(null, null)).toBeNull();
    expect(resolveLotSourceUrl("upload:tz.docx", "b2g-12")).toBeNull();
    expect(resolveLotSourceUrl(null, "12345")).toBeNull();
  });
});

describe("LotSourceLink", () => {
  it("рендерит ссылку на объявление по ID", () => {
    render(<LotSourceLink lotId="17726443" />);
    const link = screen.getByRole("link");
    expect(link).toHaveAttribute(
      "href",
      "https://goszakup.gov.kz/ru/announce/index/17726443",
    );
    expect(link).toHaveAttribute("target", "_blank");
    expect(link.getAttribute("rel")).toContain("noopener");
  });

  it("не рендерится без валидного ID — пустой ссылки быть не должно", () => {
    const { container } = render(<LotSourceLink lotId="abc" />);
    expect(container).toBeEmptyDOMElement();
  });

  it("LotSourceIconButton даёт доступное имя с номером лота", () => {
    render(<LotSourceIconButton lotId="17726443" />);
    expect(screen.getByRole("link")).toHaveAttribute(
      "aria-label",
      "Открыть лот 17726443 на Госзакупках",
    );
  });
});
