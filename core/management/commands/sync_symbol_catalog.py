from django.core.management.base import BaseCommand

from core.symbol_catalog import FutuOpenDAdapter, SUPPORTED_MARKETS, apply_catalog_snapshot


class Command(BaseCommand):
    help = "Synchronize the real provider-backed HuntAlpha security catalog."

    def add_arguments(self, parser):
        parser.add_argument("--market", choices=SUPPORTED_MARKETS, help="只同步一个市场（默认同步全部市场）")

    def handle(self, *args, **options):
        markets = [options["market"]] if options.get("market") else list(SUPPORTED_MARKETS)
        provider = FutuOpenDAdapter()
        for market in markets:
            try:
                snapshot = provider.fetch_market(market)
                stats = apply_catalog_snapshot(snapshot)
            except Exception as exc:
                self.stdout.write(
                    f"market={market} status=error error_type={type(exc).__name__}"
                )
                continue
            cap_status = "ok" if not snapshot.market_cap_error else f"error:{snapshot.market_cap_error}"
            self.stdout.write(
                "market={market} status=ok read={read} added={added} updated={updated} "
                "inactive={inactive} market_cap={market_cap} market_cap_status={cap_status}".format(
                    market=market, cap_status=cap_status, **stats,
                )
            )
