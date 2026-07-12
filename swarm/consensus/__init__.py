"""
Consensus Engine — Voting and Auction Resolution for the Hayek Economy

Adapted from NecroSwarm's 10-D Council Consensus Engine. Provides
weighted majority, Borda count, and Delphi method voting, plus
auction resolution for the HayekMAS economy.

Voting methods are callable from the HayekMAS auction loop to
resolve ties and validate outcomes.
"""

from typing import Dict, List, Any, Optional
from enum import Enum


class ConsensusMethod(Enum):
    WEIGHTED_MAJORITY = "weighted_majority"
    UNANIMOUS = "unanimous"
    SUPERMAJORITY = "supermajority"
    BORDA_COUNT = "borda_count"
    DELPHI_METHOD = "delphi_method"


class ConsensusEngine:
    """Implements consensus algorithms for the Hayek economy.

    Provides voting mechanisms that can be called from the HayekMAS
    auction loop to resolve ties, validate outcomes, and determine
    auction winners.
    """

    def __init__(self, config: Optional[Dict] = None):
        self.config = config or {}
        self.method = ConsensusMethod(
            self.config.get("consensus_method", "weighted_majority")
        )

    def calculate_weights(self, members: List[Dict],
                         confidence_scores: Dict[str, float]) -> Dict[str, float]:
        """Calculate weighted vote power for each member."""
        weights = {}

        for member in members:
            base_power = member.get("vote_power", 1)
            confidence = confidence_scores.get(member["id"], 0.5)
            tier_weight = member.get("weight", 0.5)

            weights[member["id"]] = base_power * confidence * tier_weight

        return weights

    def weighted_majority(self, proposals: List[str],
                         votes: Dict[str, str],
                         weights: Dict[str, float],
                         threshold: float = 0.6) -> Dict:
        """Weighted majority vote with confidence threshold."""
        vote_counts = {p: 0.0 for p in proposals}
        total_power = sum(weights.values())

        for member_id, proposal in votes.items():
            if proposal in vote_counts:
                vote_counts[proposal] += weights.get(member_id, 0)

        for proposal in vote_counts:
            vote_counts[proposal] = (vote_counts[proposal] / total_power
                                   if total_power > 0 else 0)

        if not vote_counts:
            return {
                "winner": None,
                "confidence": 0.0,
                "vote_distribution": {},
                "has_consensus": False,
                "method": "weighted_majority"
            }

        sorted_votes = sorted(vote_counts.items(), key=lambda x: x[1], reverse=True)
        winner = sorted_votes[0][0]
        winner_confidence = sorted_votes[0][1]

        return {
            "winner": winner if winner_confidence >= threshold else None,
            "leading_proposal": winner,
            "confidence": winner_confidence,
            "vote_distribution": vote_counts,
            "has_consensus": winner_confidence >= threshold,
            "unanimous": winner_confidence >= 0.95,
            "supermajority": winner_confidence >= 0.75,
            "method": "weighted_majority",
            "threshold": threshold
        }

    def borda_count(self, rankings: Dict[str, List[str]],
                    weights: Dict[str, float]) -> Dict:
        """Borda count for ranked preferences."""
        scores = {}

        for member_id, ranking in rankings.items():
            weight = weights.get(member_id, 1)
            n = len(ranking)

            for i, proposal in enumerate(ranking):
                points = (n - i) * weight
                scores[proposal] = scores.get(proposal, 0) + points

        if not scores:
            return {"winner": None, "scores": {}}

        winner = max(scores, key=scores.get)
        total_score = sum(scores.values())

        return {
            "winner": winner,
            "scores": scores,
            "confidence": scores[winner] / total_score if total_score > 0 else 0,
            "method": "borda_count"
        }

    def delphi_method(self, estimates: Dict[str, List[float]]) -> Dict:
        """Delphi method for numerical estimation consensus."""
        import statistics

        all_estimates = []
        for member_estimates in estimates.values():
            all_estimates.extend(member_estimates)

        if not all_estimates:
            return {"consensus": None, "confidence": 0.0}

        mean_estimate = statistics.mean(all_estimates)
        median_estimate = statistics.median(all_estimates)
        std_dev = statistics.stdev(all_estimates) if len(all_estimates) > 1 else 0

        convergence = 1.0 - (std_dev / mean_estimate if mean_estimate else 0)
        convergence = max(0, min(1, convergence))

        return {
            "consensus": median_estimate,
            "mean": mean_estimate,
            "std_dev": std_dev,
            "confidence": convergence,
            "range": (min(all_estimates), max(all_estimates)),
            "method": "delphi_method"
        }

    def resolve_auction(self, bids: Dict[str, float]) -> str:
        """
        Determine auction winner with tie-breaking.

        Args:
            bids: Dictionary mapping agent_id -> bid_price

        Returns:
            The agent_id of the winning bidder

        Tie-breaking rules:
        1. Highest bid wins
        2. If tied, first bidder (by insertion order) wins
        """
        if not bids:
            raise ValueError("Cannot resolve auction with no bids")

        max_bid = max(bids.values())
        top_bidders = [agent for agent, bid in bids.items() if bid == max_bid]

        if len(top_bidders) == 1:
            return top_bidders[0]

        # Tie-breaking: use weighted majority among tied bidders
        # (in a real system this would use agent reputation/weight)
        # For now, return the first tied bidder (stable ordering)
        return top_bidders[0]

    def quorum_check(self, present_members: int,
                    total_members: int) -> bool:
        """Check if quorum is met."""
        quorum_threshold = self.config.get("council_rules", {}).get("quorum", 0.6)
        return (present_members / total_members) >= quorum_threshold


__all__ = [
    "ConsensusEngine",
    "ConsensusMethod",
]
