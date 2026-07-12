#!/usr/bin/env python3
"""HayekSwarm — Decentralized multi-agent intelligence through Hayekian market economics.

Usage:
    python main.py                    # Run interactive demo
    python main.py train              # Run training on default domain
    python main.py train --domain math
    python main.py eval --checkpoint outputs/checkpoints/task_00100.json
"""

import argparse
import sys


def main():
    parser = argparse.ArgumentParser(
        description="HayekSwarm — Decentralized multi-agent intelligence",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "command",
        nargs="?",
        default="demo",
        choices=["demo", "train", "eval", "council", "oracle"],
        help="Command to execute (default: demo)",
    )
    parser.add_argument("--domain", default="math", help="Domain adapter to use")
    parser.add_argument("--checkpoint", help="Checkpoint path for eval/resume")
    parser.add_argument("--epochs", type=int, default=1, help="Number of training epochs")
    parser.add_argument("--tasks", type=int, default=None, help="Max tasks to process")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")

    args = parser.parse_args()

    if args.command == "demo":
        _run_demo()
    elif args.command == "train":
        _run_training(args)
    elif args.command == "eval":
        _run_eval(args)
    elif args.command == "council":
        _run_council_demo()
    elif args.command == "oracle":
        _run_oracle_demo()


def _run_demo():
    """Run an interactive demo of the Hayek economy."""
    print("🏛️  HayekSwarm Demo")
    print("=" * 60)
    print()
    print("This demo shows how the Hayek economy coordinates agents")
    print("through auctions, payments, and evolution.")
    print()
    print("To run a full training session:")
    print("  python main.py train --domain math --epochs 5")
    print()
    print("To test the pricing oracle:")
    print("  python main.py oracle")
    print()
    print("To test the 10-D council:")
    print("  python main.py council")


def _run_training(args):
    """Run training on a domain adapter."""
    print(f"🏛️  HayekSwarm Training — Domain: {args.domain}")
    print("=" * 60)
    print(f"  Epochs: {args.epochs}")
    print(f"  Max tasks: {args.tasks or 'all'}")
    print()

    if args.domain == "math":
        from hayekmas.adapters.researchworld import ResearchTrainer
        trainer = ResearchTrainer(
            num_epochs=args.epochs,
            ckpt_save_path="outputs/checkpoints",
            verbose=args.verbose,
        )
    else:
        print(f"Unknown domain: {args.domain}")
        print("Available: math, finance, research, arch_dse, cloudcast")
        sys.exit(1)

    trainer.setup(max_tasks=args.tasks)
    results = trainer.train()
    print(f"\n✅ Training complete. Results: {results}")


def _run_eval(args):
    """Run evaluation from a checkpoint."""
    if not args.checkpoint:
        print("❌ --checkpoint required for eval")
        sys.exit(1)
    print(f"🏛️  HayekSwarm Evaluation — Checkpoint: {args.checkpoint}")
    print("=" * 60)


def _run_council_demo():
    """Demonstrate the 10-D council."""
    print("🏛️  HayekSwarm 10-D Council Demo")
    print("=" * 60)
    try:
        from swarm.council.council import Council
        council = Council()
        result = council.deliberate(
            task="Design the API architecture for a distributed system",
            seats=["D1_synthesis", "D2_deep_reason", "D5_strategy"],
            stakes="high",
        )
        print(f"  Council seats: {result.get('seats', {})}")
        print(f"  Approach: {result.get('approach', 'N/A')}")
        print(f"  Verdict: {result.get('verdict', 'pending')}")
    except ImportError as e:
        print(f"  ⚠️  Council not yet built: {e}")


def _run_oracle_demo():
    """Demonstrate the pricing oracle."""
    print("🏛️  HayekSwarm Pricing Oracle Demo")
    print("=" * 60)
    try:
        from swarm.cost_router import PricingOracle, TaskProfile
        oracle = PricingOracle()
        profile = TaskProfile(
            task_id="demo-1",
            description="Design the API architecture for a distributed system",
            estimated_tokens=5000,
            requires_reasoning=True,
            requires_code=True,
            requires_creativity=False,
            deadline_ms=30000,
        )
        decision = oracle.route(profile)
        print(f"  Task: {profile.description}")
        print(f"  Model: {decision.selected_model}")
        print(f"  Cost tier: {decision.cost_tier.value}")
        print(f"  Estimated cost: ${decision.estimated_cost:.4f}")
        print(f"  Suggested bid: ${getattr(decision, 'suggested_bid', 0.0):.2f}")
    except ImportError as e:
        print(f"  ⚠️  Pricing oracle not yet built: {e}")


if __name__ == "__main__":
    main()
