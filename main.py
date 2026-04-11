"""
Product Comparison Tool — CLI entry point.

Usage:
    uv run main.py
"""

import sys
from pathlib import Path

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.prompt import Prompt, Confirm

from backend.platforms import get_platform_for_url, list_platform_names
from backend.scraper import scrape_product_with_enrichment
from backend.profiler import generate_profile
from backend.comparator import generate_comparison

console = Console()

MIN_PRODUCTS = 2
MAX_PRODUCTS = 5

# In-session state: list of (url, platform_name) tuples
_comparison_list: list[tuple[str, str]] = []


def _show_list() -> None:
    if not _comparison_list:
        console.print("[dim]No products added yet.[/dim]")
        return

    table = Table(title=f"Comparison List ({len(_comparison_list)}/{MAX_PRODUCTS})", show_lines=True)
    table.add_column("#", style="bold cyan", width=4)
    table.add_column("Platform", style="bold", width=10)
    table.add_column("URL")

    for i, (url, platform) in enumerate(_comparison_list, 1):
        display_url = url if len(url) <= 80 else url[:77] + "..."
        table.add_row(str(i), platform, display_url)

    console.print(table)


def _add_product(url: str) -> None:
    url = url.strip()
    if not url:
        console.print("[red]No URL provided.[/red]")
        return

    platform = get_platform_for_url(url)
    if not platform:
        supported = ", ".join(list_platform_names())
        console.print(
            f"[red]Unsupported platform.[/red] "
            f"Currently supported: [bold]{supported}[/bold]"
        )
        return

    if len(_comparison_list) >= MAX_PRODUCTS:
        console.print(f"[red]Maximum of {MAX_PRODUCTS} products reached.[/red]")
        return

    if any(existing_url == url for existing_url, _ in _comparison_list):
        console.print("[yellow]This URL is already in the list.[/yellow]")
        return

    _comparison_list.append((url, platform.name))
    console.print(f"[green]Added[/green] ({platform.name}): {url[:80]}")
    console.print(
        f"[dim]List: {len(_comparison_list)}/{MAX_PRODUCTS} products. "
        f"Need at least {MIN_PRODUCTS} to compare.[/dim]"
    )


def _remove_product() -> None:
    if not _comparison_list:
        console.print("[red]The list is empty.[/red]")
        return

    _show_list()
    idx_str = Prompt.ask("Enter the number to remove")
    try:
        idx = int(idx_str) - 1
        if 0 <= idx < len(_comparison_list):
            removed_url, removed_platform = _comparison_list.pop(idx)
            console.print(f"[green]Removed[/green] ({removed_platform}): {removed_url[:80]}")
        else:
            console.print("[red]Invalid number.[/red]")
    except ValueError:
        console.print("[red]Please enter a valid number.[/red]")


def _run_comparison() -> None:
    if len(_comparison_list) < MIN_PRODUCTS:
        console.print(
            f"[red]Need at least {MIN_PRODUCTS} products to compare. "
            f"Currently have {len(_comparison_list)}.[/red]"
        )
        return

    console.rule("[bold blue]Fetching & Analyzing Products")
    profiles = []

    for i, (url, platform_name) in enumerate(_comparison_list, 1):
        # Step 1: scrape
        with console.status(
            f"[{i}/{len(_comparison_list)}] Scraping {platform_name}: {url[:55]}..."
        ):
            try:
                product_data = scrape_product_with_enrichment(url)
            except Exception as e:
                console.print(f"[red]Failed to scrape:[/red] {e}")
                return

        # Step 2: profile
        with console.status(
            f"[{i}/{len(_comparison_list)}] Generating profile: {product_data.title[:50]}..."
        ):
            try:
                profile = generate_profile(product_data)
                profiles.append(profile)
                console.print(
                    f"[green]✓[/green] [{i}/{len(_comparison_list)}] {profile.title[:65]}"
                )
            except Exception as e:
                console.print(f"[red]Failed to generate profile:[/red] {e}")
                return

    console.rule("[bold blue]Generating Comparison")
    with console.status("Comparing products and writing recommendation..."):
        try:
            comparison = generate_comparison(profiles)
        except Exception as e:
            console.print(f"[red]Failed to generate comparison:[/red] {e}")
            return

    console.print()
    console.print(Panel(comparison.summary, title="[bold]Comparison Summary[/bold]", border_style="blue"))
    console.print()
    console.print(Panel(comparison.recommendation, title="[bold]Recommendation[/bold]", border_style="green"))
    console.print()

    if Confirm.ask("Download comparison as a Markdown file?"):
        output_path = Path("comparison_output.md")
        output_path.write_text(comparison.markdown, encoding="utf-8")
        console.print(f"[green]Saved →[/green] {output_path.resolve()}")


def _show_menu() -> None:
    console.print("\n[bold]What would you like to do?[/bold]")
    console.print("  [cyan]add[/cyan]     — Add a product URL to the list")
    console.print("  [cyan]list[/cyan]    — Show the current comparison list")
    console.print("  [cyan]remove[/cyan]  — Remove a product from the list")
    console.print("  [cyan]compare[/cyan] — Fetch data and generate the comparison")
    console.print("  [cyan]quit[/cyan]    — Exit\n")


def main() -> None:
    supported = ", ".join(list_platform_names())
    console.print(
        Panel.fit(
            f"[bold]Product Comparison Tool[/bold]\n"
            f"[dim]Supported platforms (Phase 1): {supported}[/dim]\n"
            f"[dim]Add {MIN_PRODUCTS}–{MAX_PRODUCTS} products, then click compare.[/dim]",
            border_style="blue",
        )
    )

    while True:
        _show_menu()
        choice = Prompt.ask(
            "Action",
            choices=["add", "list", "remove", "compare", "quit"],
        )

        if choice == "add":
            url = Prompt.ask("Product URL")
            _add_product(url)

        elif choice == "list":
            _show_list()

        elif choice == "remove":
            _remove_product()

        elif choice == "compare":
            _run_comparison()

        elif choice == "quit":
            console.print("[dim]Goodbye.[/dim]")
            sys.exit(0)


if __name__ == "__main__":
    main()
