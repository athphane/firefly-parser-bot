from datetime import datetime


class ParsedTransactionMessage:
    def __init__(
            self,
            card: str,
            date: str,
            time: str,
            currency: str,
            amount: str,
            location: str,
            approval_code: str,
            reference_no: str,
    ):
        self.card = card
        self.date = date
        self.time = time
        self.currency = currency
        self.amount = amount
        self.location = location
        self.approval_code = approval_code
        self.reference_no = reference_no
        self.is_receipt = False

    @staticmethod
    def make(data):
        return ParsedTransactionMessage(
            card=data['card'],
            date=data['date'],
            time=data['time'],
            currency=data['currency'],
            amount=data['amount'],
            location=data['location'],
            approval_code=data['approval_code'],
            reference_no=data['reference_no'],
        )

    def getDate(self, is_recept: bool = False):
        if is_recept:
            self.is_receipt = True

        date_format = '%d/%m/%Y %H:%i' if self.is_receipt else '%d/%m/%y %H:%i:%s'

        datetime_string = f"{self.date} {self.time}"

        try:
            return datetime.strptime(datetime_string, date_format)
        except ValueError as e:
            print(f"Error parsing date: {e}.  datetime_string: {datetime_string}, format_string: {date_format}")

        return None

    def get_first_similar_account_name(self):
        pass
