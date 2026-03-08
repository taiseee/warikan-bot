# groups
## column
id: int
conversation_id: string
created_at: datetime
updated_at: datetime
## subcollection
payers

# payers
## column
id: int
name: string
## subcollection
statements

# statements
## column
id: int
amount: int