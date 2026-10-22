# Contract: Business Profile & Generic Intake

## Models

### IntakeDetailType
Enum: `general`, `asset_type`, `brand`, `model`, `serial_number`.
User-facing labels:
- `general`: "General detail"
- `asset_type`: "Asset type"
- `brand`: "Brand"
- `model`: "Model"
- `serial_number`: "Serial number"

### IntakeField
```python
class IntakeField(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    key: str = Field(pattern=r"^[a-z][a-z0-9_]{0,39}$")
    detail_type: Literal["general", "asset_type", "brand", "model", "serial_number"] = "general"
    label: str = Field(min_length=1, max_length=80)
    type: Literal["text", "number"] = "text"
    required: bool = False

    @field_validator("type")
    @classmethod
    def validate_type_for_detail(cls, v, info):
        # Identifiers (serial_number) remain text
        detail_type = info.data.get("detail_type")
        if detail_type in ("serial_number", "brand", "model", "asset_type") and v == "number":
            # If user explicitly requested number on general, allowed; identifiers remain text
            if detail_type == "serial_number":
                raise ValueError("Serial numbers must be text")
        return v
```

### BusinessProfile
```python
class BusinessProfile(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    industry: str = Field(default="Service business", min_length=1, max_length=100)
    collect_vehicle_details: bool = False
    intake_fields: list[IntakeField] = Field(default_factory=list, max_length=20)
```

## Legacy Compatibility & Defaults
If `intake_fields` is empty in configuration or when initializing generic equivalents for an automotive setup:
- `make` -> `detail_type`: `brand`, `label`: `Make`, `type`: `text`, `required`: False
- `model` -> `detail_type`: `model`, `label`: `Model`, `type`: `text`, `required`: False
- `year` -> `detail_type`: `general`, `label`: `Year`, `type`: `number`, `required`: False

## Prompt Guidance Contract
`build_business_prompt(config)`:
- Required fields: listed with their business labels and explicit instruction to ask one at a time.
- Optional fields: listed with their business labels and explicit instruction NOT to solicit or ask questions for them, but to record volunteered details into `intake_data_json`.
- Generic requests store data in `intake_data` JSONB.
- No dummy row is inserted into `vehicles` table when `collect_vehicle_details` is False or when no vehicle is provided.
