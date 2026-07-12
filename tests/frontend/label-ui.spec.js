const { test, expect } = require("@playwright/test");

const fields = {
  brand_name: "Acme Reserve",
  class_type: "Red Wine",
  producer: "Acme Winery LLC",
  country_of_origin: "United States",
  abv: "13.5",
  net_contents: "750 ml",
  government_warning: "GOVERNMENT WARNING: exact text",
};

const passResponse = {
  summary: { passed: 1, needs_review: 0, total: 1, latency_ms: 1200 },
  results: [
    {
      index: 0,
      filename: "label.jpg",
      status: "PASS",
      latency_ms: 1100,
      errors: {},
      extracted_label: {
        brand_name: "Acme Reserve",
        class_type: "Red Wine",
        producer: "Acme Winery LLC",
        country_of_origin: "USA",
        abv: "13.5% Alc. by Vol.",
        net_contents: "750 ml",
        government_warning: "GOVERNMENT WARNING: exact text",
      },
      verification: {
        verdict: "PASS",
        fields: Object.keys(fields).map((field) => ({
          field,
          status: "PASS",
          application_value: fields[field],
          extracted_value: field === "country_of_origin" ? "USA" : fields[field],
          strategy: "test",
          score: 100,
          normalized_application_value: null,
          normalized_extracted_value: null,
          message: "Looks good.",
        })),
      },
    },
  ],
};

const mixedBatchResponse = {
  summary: { passed: 1, needs_review: 1, total: 2, latency_ms: 1800 },
  results: [
    passResponse.results[0],
    {
      ...passResponse.results[0],
      index: 1,
      filename: "label-2.jpg",
      status: "NEEDS_REVIEW",
      verification: {
        verdict: "NEEDS_REVIEW",
        fields: [
          {
            field: "brand_name",
            status: "FAIL",
            application_value: "Acme Reserve",
            extracted_value: "Wrong Brand",
            strategy: "test",
            score: 20,
            normalized_application_value: null,
            normalized_extracted_value: null,
            message: "These do not match closely enough.",
          },
        ],
      },
    },
  ],
};

async function setImage(card, name = "label.jpg") {
  await card.locator('[data-field="image"]').setInputFiles({
    name,
    mimeType: "image/jpeg",
    buffer: Buffer.from("fake image bytes"),
  });
}

async function fillCard(card) {
  await setImage(card);
  await card.locator('[data-field="brand_name"]').fill(fields.brand_name);
  await card.locator('[data-field="class_type"]').fill(fields.class_type);
  await card.locator('[data-field="producer"]').fill(fields.producer);
  await card.locator('[data-field="country_of_origin"]').selectOption(fields.country_of_origin);
  await card.locator('[data-field="abv"]').fill(fields.abv);
  await card.locator('[data-field="net_contents"]').selectOption(fields.net_contents);
  await card.locator('[data-field="government_warning"]').fill(fields.government_warning);
}

test("page starts with one completeable label card and plain labels", async ({ page }) => {
  await page.goto("/");

  await expect(page.locator(".label-card")).toHaveCount(1);
  await expect(page.getByText("Brand name")).toBeVisible();
  await expect(page.getByText("Product type")).toBeVisible();
  await expect(page.getByText("Producer or company")).toBeVisible();
  await expect(page.getByText("Government warning")).toBeVisible();
  await expect(page.getByText(/mode selector/i)).toHaveCount(0);
  await expect(page.locator("#submit-button")).toBeDisabled();

  await fillCard(page.locator(".label-card").first());
  await expect(page.locator("#submit-button")).toBeEnabled();
  await expect(page.locator("#submit-button")).toHaveText("Check Label");
});

test("batch cards update controls and expose view details", async ({ page }) => {
  await page.route("**/verify/batch", async (route) => {
    await route.fulfill({ json: mixedBatchResponse });
  });
  await page.goto("/");

  await fillCard(page.locator(".label-card").first());
  await page.locator("#add-label-button").click();
  await expect(page.locator(".label-card")).toHaveCount(2);
  await fillCard(page.locator(".label-card").nth(1));

  await expect(page.locator(".remove-label").first()).toBeVisible();
  await expect(page.locator("#submit-button")).toHaveText("Check All Labels");
  await page.locator("#submit-button").click();

  await expect(page.locator("#verdict-badge")).toHaveText("NEEDS REVIEW");
  await expect(page.locator("#batch-summary")).toContainText("1");
  await expect(page.locator(".details-action").first()).toHaveText("View details");
  await page.locator(".batch-result").nth(1).locator("summary").click();
  await expect(page.locator(".batch-result").nth(1)).toContainText("Expected");
  await expect(page.locator(".batch-result").nth(1)).toContainText("Wrong Brand");
});

test("plain english server errors focus the error panel", async ({ page }) => {
  await page.route("**/verify/batch", async (route) => {
    await route.fulfill({
      status: 415,
      json: {
        message: "Please provide an image and all required label fields.",
        errors: { image: "Unsupported file type." },
      },
    });
  });
  await page.goto("/");

  await fillCard(page.locator(".label-card").first());
  await page.locator("#submit-button").click();

  await expect(page.locator("#message")).toContainText("Please choose a JPG, PNG, or WebP photo.");
  await expect(page.locator("#message")).toBeFocused();
});

test("mobile layout does not create horizontal overflow", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 900 });
  await page.goto("/");

  const hasOverflow = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth);
  expect(hasOverflow).toBe(false);
});
