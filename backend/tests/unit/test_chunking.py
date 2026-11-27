from app.rag.chunking import chunk_by_heading, chunk_fixed, chunk_parent_child

POLICY = "# Refunds\nFull refund in 14 days.\n# Shipping\nShips in 2 days.\n"


def test_fixed_chunks_split_long_text_with_overlap():
    text = " ".join(f"w{i}" for i in range(100))

    chunks = chunk_fixed(text, size_tokens=20, overlap_ratio=0.1)

    assert len(chunks) > 1
    assert all(c.strategy == "fixed" for c in chunks)
    assert [c.index for c in chunks] == list(range(len(chunks)))
    assert all(len(c.text.split()) <= 20 for c in chunks)
    first_tail = chunks[0].text.split()[-2:]
    assert chunks[1].text.split()[:2] == first_tail
    assert {f"w{i}" for i in range(100)} <= {w for c in chunks for w in c.text.split()}


def test_fixed_chunk_empty_text_returns_nothing():
    assert chunk_fixed("   \n ") == []


def test_heading_chunk_keeps_refund_section_together():
    chunks = chunk_by_heading(POLICY, max_tokens=200, overlap_ratio=0.1)

    assert any("14 days" in c.text and "Ships" not in c.text for c in chunks)
    refund = next(c for c in chunks if "14 days" in c.text)
    assert refund.section == "Refunds"
    assert refund.strategy == "heading"


def test_heading_chunk_splits_oversized_section_and_keeps_section():
    body = " ".join(f"w{i}" for i in range(60))

    chunks = chunk_by_heading(f"# Big\n{body}\n", max_tokens=20, overlap_ratio=0.1)

    assert len(chunks) > 1
    assert {c.section for c in chunks} == {"Big"}


def test_heading_chunk_keeps_faq_blocks_atomic():
    text = (
        "Q: How do I reset my password?\nA: Use the reset link.\n\n"
        "Q: Can I change my plan?\nA: Yes, any time in billing.\n"
    )

    chunks = chunk_by_heading(text, max_tokens=200, overlap_ratio=0.1)

    assert len(chunks) == 2
    assert "reset link" in chunks[0].text and "billing" not in chunks[0].text
    assert chunks[1].section == "Can I change my plan?"


def test_heading_chunk_without_headings_uses_whole_text():
    chunks = chunk_by_heading("Plain note about returns.", max_tokens=200)

    assert [c.text for c in chunks] == ["Plain note about returns."]
    assert chunks[0].section is None


def test_parent_child_sets_parent_text_on_each_child():
    long_body = " ".join(f"refund{i}" for i in range(80))
    text = f"# Refunds\n{long_body}\n# Shipping\nShips in 2 days.\n"

    chunks = chunk_parent_child(text, child_tokens=20, parent_tokens=200)

    refund_children = [c for c in chunks if c.section == "Refunds"]
    assert len(refund_children) > 1
    assert all(c.strategy == "parent_child" for c in chunks)
    assert all(c.parent_text and long_body in c.parent_text for c in refund_children)
    assert all(len(c.text.split()) <= 20 for c in refund_children)
    shipping = next(c for c in chunks if c.section == "Shipping")
    assert "Ships in 2 days." in shipping.parent_text
    assert [c.index for c in chunks] == list(range(len(chunks)))


def test_heading_only_blocks_do_not_become_chunks():
    text = "# Policy\n## Refunds\nFull refund in 14 days.\n## Empty\n"

    chunks = chunk_by_heading(text, max_tokens=200)

    assert [c.section for c in chunks] == ["Refunds"]
