const { test, expect } = require("@playwright/test");

const fields = {
  brand_name: "Acme Reserve",
  class_type: "Wine",
  producer: "Acme Winery LLC",
  country_of_origin: "United States",
  abv: "13.5",
  net_contents: "750 ml",
  government_warning: "GOVERNMENT WARNING: exact text",
};

const passResponse = {
  summary: { passed: 1, needs_review: 0, total: 1 },
  items: [
    {
      index: 0,
      filename: "label.jpg",
      status: "APPROVED",
      latency_ms: 1100,
      errors: {},
      extracted_label: {
        brand_name: "Acme Reserve",
        class_type: "Wine",
        producer: "Acme Winery LLC",
        country_of_origin: "USA",
        abv: "13.5% Alc. by Vol.",
        net_contents: "750 ml",
        government_warning: "GOVERNMENT WARNING: exact text",
      },
      verification: {
        overall_verdict: "APPROVED",
        latency_ms: 100,
        results: Object.keys(fields).map((field) => ({
          field,
          status: "PASS",
          expected: fields[field],
          found: field === "country_of_origin" ? "USA" : fields[field],
          match_type: "test",
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
  summary: { passed: 1, needs_review: 1, total: 2 },
  items: [
    passResponse.items[0],
    {
      ...passResponse.items[0],
      index: 1,
      filename: "label-2.jpg",
      status: "NEEDS_REVIEW",
      verification: {
        overall_verdict: "NEEDS_REVIEW",
        latency_ms: 100,
        results: [
          {
            field: "brand_name",
            status: "FAIL",
            expected: "Acme Reserve",
            found: "Wrong Brand",
            match_type: "test",
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

const unreadableBatchResponse = {
  summary: { passed: 0, needs_review: 2, total: 2 },
  items: [
    {
      ...passResponse.items[0],
      status: "NEEDS_REVIEW",
      vision_extraction_failed: true,
      verification: {
        overall_verdict: "NEEDS_REVIEW",
        latency_ms: 100,
        results: Object.keys(fields).map((field) => ({
          field,
          status: "FAIL",
          expected: fields[field],
          found: null,
          match_type: "test",
          score: null,
          normalized_application_value: null,
          normalized_extracted_value: null,
          message: "Extracted value is missing.",
        })),
      },
    },
    {
      ...passResponse.items[0],
      index: 1,
      filename: "label-2.jpg",
      status: "NEEDS_REVIEW",
      vision_extraction_failed: true,
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
  await card.locator('[data-field="class_type"]').selectOption(fields.class_type);
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
  await expect(page.locator('label[for="label-1-class_type"]')).toHaveText("Product type");
  await expect(page.getByText("Producer or company")).toBeVisible();
  await expect(page.getByText("Government warning")).toBeVisible();
  await expect(page.getByText(/mode selector/i)).toHaveCount(0);
  await expect(page.locator("#submit-button")).toBeDisabled();

  await fillCard(page.locator(".label-card").first());
  await expect(page.locator("#submit-button")).toBeEnabled();
  await expect(page.locator("#submit-button")).toHaveText("Check Label");
});

test("selected label photo preview gets descriptive alt text", async ({ page }) => {
  await page.goto("/");

  const card = page.locator(".label-card").first();
  await expect(card.locator(".image-preview")).toHaveAttribute("alt", "");
  await setImage(card, "sample-label.jpg");
  await expect(card.locator(".image-preview")).toHaveAttribute("alt", "Preview of sample-label.jpg");
});

test("cloned label cards keep accessible label associations unique", async ({ page }) => {
  await page.goto("/");

  await page.locator("#add-label-button").click();
  await page.locator("#add-label-button").click();
  await expect(page.locator(".label-card")).toHaveCount(3);

  const accessibilityState = await page.evaluate(() => {
    const ids = [...document.querySelectorAll("[id]")].map((element) => element.id);
    const duplicateIds = ids.filter((id, index) => ids.indexOf(id) !== index);
    const missingLabelTargets = [...document.querySelectorAll("label")]
      .map((label) => label.getAttribute("for"))
      .filter((targetId) => !targetId || !document.getElementById(targetId));
    const otherInputs = [...document.querySelectorAll(".other-input")].map((input) => ({
      id: input.id,
      ariaLabel: input.getAttribute("aria-label"),
    }));

    return { duplicateIds, missingLabelTargets, otherInputs };
  });

  expect(accessibilityState.duplicateIds).toEqual([]);
  expect(accessibilityState.missingLabelTargets).toEqual([]);
  expect(accessibilityState.otherInputs).toEqual([
    { id: "label-1-class-type-other", ariaLabel: "Enter product type" },
    { id: "label-1-country-other", ariaLabel: "Enter country" },
    { id: "label-2-class-type-other", ariaLabel: "Enter product type" },
    { id: "label-2-country-other", ariaLabel: "Enter country" },
    { id: "label-3-class-type-other", ariaLabel: "Enter product type" },
    { id: "label-3-country-other", ariaLabel: "Enter country" },
  ]);
});

test("product type other option submits the typed value", async ({ page }) => {
  let submittedItems = null;
  await page.route("**/verify/batch", async (route) => {
    const postData = route.request().postData() || "";
    const match = postData.match(/name="items_json"\r\n\r\n([^\r]+)\r\n/);
    submittedItems = match ? JSON.parse(match[1]) : null;
    await route.fulfill({ json: passResponse });
  });
  await page.goto("/");

  const card = page.locator(".label-card").first();
  await fillCard(card);
  await card.locator('[data-field="class_type"]').selectOption("__other__");
  await expect(card.locator('[data-field-row="class_type"] .other-input')).toBeVisible();
  await card.locator('[data-field-row="class_type"] .other-input').fill("Agave Spirit");
  await expect(page.locator("#submit-button")).toBeEnabled();
  await page.locator("#submit-button").click();

  expect(submittedItems?.[0]?.class_type).toBe("Agave Spirit");
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

test("unreadable photos show one clear retry message", async ({ page }) => {
  await page.route("**/verify/batch", async (route) => {
    await route.fulfill({ json: unreadableBatchResponse });
  });
  await page.goto("/");

  await fillCard(page.locator(".label-card").first());
  await page.locator("#add-label-button").click();
  await fillCard(page.locator(".label-card").nth(1));
  await page.locator("#submit-button").click();

  await expect(page.locator(".label-card").first()).toContainText("We couldn't read this photo");
  await expect(page.locator(".label-card").first().locator(".inline-result.suppressed")).toHaveCount(6);
  await page.locator(".batch-result").nth(1).locator("summary").click();
  await expect(page.locator(".batch-result").nth(1)).toContainText("We couldn't read this photo");
  await expect(page.locator(".batch-result").nth(1)).not.toContainText("Expected");
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
