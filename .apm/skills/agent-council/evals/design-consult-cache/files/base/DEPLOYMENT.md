# Deployment

- 2 app hosts behind a load balancer, each running gunicorn with 4 sync workers (8 processes total).
- Product catalog: ~40k products; ~95% of product-page traffic hits the top 2k products.
- Prices are edited by the merchandising team in the admin tool; the business requires a price
  change to be visible on product pages within 5 seconds.
- Infra today: Postgres (managed). No Redis or other cache service is provisioned yet.
- Team: 3 backend engineers; on-call is shared with the platform team.
