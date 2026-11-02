"""Structured output — validated data or a typed error, never raw strings.

The competitor-parity capability: ZYKO enforces a JSON Schema on the answer,
extracts the payload from any messy model output, and repairs invalid
answers once by feeding the validation errors back to the model.

    ZYKO_DEMO=1 python examples/06_structured.py
"""

from zyko import Zyko, StructuredOutputError

ORDER_SCHEMA = {
    "type": "object",
    "properties": {
        "id": {"type": "integer"},
        "status": {"type": "string", "enum": ["open", "shipped", "cancelled"]},
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"sku": {"type": "string"}, "qty": {"type": "integer", "minimum": 1}},
                "required": ["sku", "qty"],
            },
        },
    },
    "required": ["id", "status"],
}


def main() -> None:
    zk = Zyko()  # ZYKO_DEMO=1 for the keyless mock provider

    # 1. guided mode (default): schema rides the prompt; the reply is
    #    extracted, validated, and repaired once if it fails.
    out = zk.structured(
        "Order 42: shipped, one widget (sku W-1, qty 2). Reply as JSON.",
        schema=ORDER_SCHEMA,
        system="You extract structured data.",
    )
    print("data:", out.data)
    print("repaired:", out.repaired)
    print("rounds:", out.rounds)
    print("routed via:", out.route.candidate)

    # 2. Pydantic interop (pip install 'zyko[structured]'):
    #    from pydantic import BaseModel
    #    class Order(BaseModel):
    #        id: int
    #        status: str
    #    out = zk.structured("...", schema=Order)   # out.data is a dict

    # 3. typed failure when the model keeps missing the schema:
    try:
        zk.structured("reply with nonsense", schema=ORDER_SCHEMA, max_repairs=0)
    except StructuredOutputError as exc:
        print("validation errors:", exc.errors)


if __name__ == "__main__":
    main()
