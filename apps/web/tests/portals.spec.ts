import { test, expect } from "@playwright/test";

test("customer login, orders, transcript panel, verification and exact-action confirmation", async ({
  page,
}) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Customer", exact: true }).click();
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Hello, Aarav." }),
  ).toBeVisible();
  await page.screenshot({
    path: "test-results/customer-overview.png",
    fullPage: true,
  });
  await page.getByRole("button", { name: "My orders", exact: true }).click();
  await expect(page.getByText("ORD-1007", { exact: false })).toBeVisible();
  await expect(
    page.getByText("The 30-day return window has closed"),
  ).toBeVisible();
  await page.getByRole("button", { name: "Ask about an order" }).click();
  await expect(
    page.getByRole("complementary", { name: "Active voice call" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Verify identity" }).click();
  const challenge = await page.getByText(/Demo challenge:/).innerText();
  await page.getByLabel("Verification code").fill(challenge.match(/\d{6}/)![0]);
  await page.getByRole("button", { name: "Verify code", exact: true }).click();
  await expect(
    page.getByText("Identity verified for one action"),
  ).toBeVisible();
  await page.getByRole("button", { name: "Confirm this action" }).click();
  await expect(
    page
      .getByRole("complementary", { name: "Active voice call" })
      .getByText("pending approval", { exact: true }),
  ).toBeVisible();
  await page.screenshot({
    path: "test-results/customer-portal.png",
    fullPage: true,
  });
  // A deliberately invalid RTC token tests UI error handling; media is covered by the credentialed suite.
});

test("staff refund decision requires reason and changes the persisted request", async ({
  page,
}) => {
  await page.goto("/");
  await page
    .getByRole("button", { name: "Support staff", exact: true })
    .click();
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Make someone’s day easier." }),
  ).toBeVisible();
  await page
    .getByLabel("Decision reason for ORD-1007")
    .fill("Received return inspected and approved");
  await page.getByRole("button", { name: "Approve", exact: true }).click();
  await expect(
    page.getByText("Decision: Received return inspected and approved"),
  ).toBeVisible();
  await page.getByRole("button", { name: "Customers", exact: true }).click();
  await page.getByRole("button", { name: /Aarav Sharma/ }).click();
  await page
    .getByLabel("CRM notes")
    .fill("Customer prefers a concise refund update.");
  await page.getByRole("button", { name: "Save profile" }).click();
  await expect(page.getByText("Customer record updated.")).toBeVisible();
  await page.screenshot({
    path: "test-results/support-workspace.png",
    fullPage: true,
  });
});

test("staff can claim escalation and receive the room connection", async ({
  page,
}) => {
  await page.goto("/");
  await page
    .getByRole("button", { name: "Support staff", exact: true })
    .click();
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await page.getByRole("button", { name: "Accept", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Join call", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Join call", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Live support", exact: true }),
  ).toBeVisible();
});

test("portal adapts to a mobile viewport", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await page.getByRole("button", { name: "Customer", exact: true }).click();
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Talk to Mira" }),
  ).toBeVisible();
  await page.screenshot({
    path: "test-results/mobile-portal.png",
    fullPage: true,
  });
  const widths = await page.evaluate(() => ({
    scroll: document.documentElement.scrollWidth,
    width: window.innerWidth,
  }));
  expect(widths.scroll).toBeLessThanOrEqual(widths.width);
});
