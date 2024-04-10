# groups
## column
id: int
thread_id: int
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