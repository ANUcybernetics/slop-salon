export default {
  extends: ["stylelint-config-standard"],
  overrides: [
    {
      files: ["**/*.astro"],
      customSyntax: "postcss-html",
    },
  ],
  rules: {
    "no-descending-specificity": null,
  },
};
