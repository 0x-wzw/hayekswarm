from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Set, Dict
import collections
import re

@dataclass
class SemanticLink:
    entity: str
    sessions: Set[str] = field(default_factory=set)
    weight: float = 1.0

class SemanticRegistry:
    """
    The Semantic Registry tracks entities across different sessions.
    It allows the Hub to discover 'latent links' between disparate conversations
    based on shared conceptual entities.
    """
    def __init__(self):
        # entity_name -> set of session_ids
        self._entity_map: Dict[str, Set[str]] = collections.defaultdict(set)
        # session_id -> set of entities mentioned
        self._session_map: Dict[str, Set[str]] = collections.defaultdict(set)

    def extract_entities(self, text: str) -> Set[str]:
        """
        Lightweight entity extraction. 
        In a production environment, this would use a NER (Named Entity Recognition) model.
        Here, we use a pattern-based approach for proper nouns and capitalized terms.
        """
        words = re.findall(r'\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\b', text)
        # Filter out common stop-words that might be capitalized
        stop_words = {'The', 'A', 'An', 'I', 'This', 'That', 'It', 'He', 'She', 'They'}
        return {w for w in words if w not in stop_words}

    def register_event(self, session_id: str, text: str):
        """Links a session to the entities found in a message."""
        entities = self.extract_entities(text)
        for entity in entities:
            self._entity_map[entity].add(session_id)
            self._session_map[session_id].add(entity)

    def get_related_sessions(self, session_id: str) -> Dict[str, float]:
        """
        Finds sessions related to the target session.
        Score is based on the number of shared entities.
        """
        if session_id not in self._session_map:
            return {}

        my_entities = self._session_map[session_id]
        related = collections.defaultdict(float)

        for entity in my_entities:
            for other_session in self._entity_map[entity]:
                if other_session != session_id:
                    related[other_session] += 1.0
        
        return dict(related)

    def get_entities_for_session(self, session_id: str) -> Set[str]:
        return self._session_map.get(session_id, set())

# Global singleton for the Hub
registry = SemanticRegistry()
