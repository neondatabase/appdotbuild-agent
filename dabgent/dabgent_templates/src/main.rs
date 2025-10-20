use dabgent_templates::TemplateTRPC;

fn main() {
    println!("TemplateTRPC files");
    for file in TemplateTRPC::iter() {
        println!("File: {file}");
    }
}
